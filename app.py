import json
import os
import boto3
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import text, desc, func, case, cast, Integer, select
from sqlalchemy.orm import joinedload
from dotenv import load_dotenv
from datetime import datetime
import re, time
from datetime import datetime

# from app import db
# 載入本地 .env 環境變數
load_dotenv()

app = Flask(__name__)

# Flask-Login 配置
app.secret_key = "your_secret_key"  # 用于加密会话
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "index"  # 未登入時會重定向到 login 頁面


# 設定 AWS S3
S3_BUCKET = "ntusc-files"
S3_REGION = "ap-southeast-1"  # 修改為你的 AWS 區域
S3_KEY = os.getenv("AWS_ACCESS_KEY_ID")
S3_SECRET = os.getenv("AWS_SECRET_ACCESS_KEY")

s3 = boto3.client(
    "s3",
    aws_access_key_id=S3_KEY,
    aws_secret_access_key=S3_SECRET,
    region_name=S3_REGION,
)

# 設定 SQLAlchemy 資料庫連線
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "default-secret")

db = SQLAlchemy(app)


# 假设文章存储在字典中
articles = {}
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# 用戶帳號與密碼表
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

    # 一個用戶可以擁有多條通知和紀錄
    notifications = db.relationship("Notification", backref="user", lazy=True)
    records = db.relationship("Record", backref="user", lazy=True)

    def __repr__(self):
        return f"<User {self.username}>"


# 通知資料表
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    session = db.Column(db.Integer, nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    place = db.Column(db.String(100), nullable=False)
    person = db.Column(db.String(100), nullable=True)
    shorthand = db.Column(db.String(255), nullable=True)
    attendance = db.Column(JSONB, nullable=False)  # 不允許為NULL
    present = db.Column(JSONB, nullable=False)  # 不允許為NULL
    is_visible = db.Column(db.Boolean, default=True, nullable=False)

    record_id = db.Column(
        db.Integer,
        db.ForeignKey("record.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
    )

    record = db.relationship(
        "Record", backref=db.backref("notification", uselist=False)
    )

    # 外鍵連接到用戶
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )

    # 外鍵連接到多個排程
    schedules = db.relationship(
        "Schedule", backref="notification", cascade="all, delete-orphan", lazy=True
    )

    def __repr__(self):
        return f"<Notification {self.title}>"


# 紀錄資料表
class Record(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    session = db.Column(db.Integer, nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    place = db.Column(db.String(100), nullable=False)
    person = db.Column(db.String(100), nullable=True)
    shorthand = db.Column(db.String(255), nullable=True)
    attendance = db.Column(JSONB, nullable=False)  # 不允許為NULL
    present = db.Column(JSONB, nullable=False)
    is_visible = db.Column(db.Boolean, default=True, nullable=False)
    is_modify = db.Column(db.Boolean, default=False, nullable=False)

    # 外鍵連接到用戶
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )

    # 外鍵連接到多個排程
    schedules = db.relationship(
        "Schedule", backref="record", cascade="all, delete-orphan", lazy=True
    )

    def __repr__(self):
        return f"<Record {self.title}>"


# Schedule 表格
class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    notification_id = db.Column(
        db.Integer, db.ForeignKey("notification.id", ondelete="CASCADE"), nullable=True
    )
    record_id = db.Column(
        db.Integer, db.ForeignKey("record.id", ondelete="CASCADE"), nullable=True
    )

    # 與 Detail 關聯
    details = db.relationship(
        "Detail", backref="schedule", cascade="all, delete-orphan", lazy="joined"
    )

    def __repr__(self):
        return f"<Schedule {self.title}>"


detail_file = db.Table(
    "detail_file",
    db.Column(
        "detail_id",
        db.Integer,
        db.ForeignKey("detail.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "file_id",
        db.Integer,
        db.ForeignKey("file.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Detail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=True)
    schedule_id = db.Column(
        db.Integer, db.ForeignKey("schedule.id", ondelete="CASCADE"), nullable=False
    )

    files = db.relationship("File", secondary=detail_file, backref="details")

    def __repr__(self):
        return f"<Detail {self.id}>"


class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(255), nullable=False)
    filename_with_timestamp = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f"<File {self.original_filename}>"


# 創建資料庫表格
with app.app_context():
    db.create_all()


# 刪除整個資料表（包括資料與結構）
def drop_table(YourModel):
    with app.app_context():
        try:
            YourModel.__table__.drop(db.engine)
            print("資料表已成功刪除。")
        except Exception as e:
            print("刪除失敗：", e)


# drop_table(File)
# drop_table(Detail)


# 創建測試資料的函數
def create_test_user():
    with app.app_context():
        # 設定測試用戶名和密碼
        username = "123"
        password = "123"  # 密碼可以是任意的

        # 檢查使用者是否已經存在
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            print(f"User '{username}' already exists.")
            return
        # 密碼加密
        hashed_password = password

        # 創建新的使用者
        new_user = User(username=username, password=hashed_password)

        # 將新的使用者物件加入資料庫
        db.session.add(new_user)
        db.session.commit()
        print(f"User '{username}' created successfully.")


# 呼叫創建測試用戶的函數
# create_test_user()

# 中文數字對應字典
chinese_numbers = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
    "十三": 13,
    "十四": 14,
    "十五": 15,
    "十六": 16,
    "十七": 17,
    "十八": 18,
    "十九": 19,
    "二十": 20,
    "二十一": 21,
    "二十二": 22,
    "二十三": 23,
    "二十四": 24,
    "二十五": 25,
    "二十六": 26,
    "二十七": 27,
    "二十八": 28,
    "二十九": 29,
    "三十": 30,
}


# 函數：將 "第xx屆" 轉換為數字
def chinese_to_number(chinese_str):
    # 使用正則表達式匹配 "第xx屆" 格式的字串
    match = re.match(r"第([一二三四五六七八九十]+)屆", chinese_str)
    if match:
        chinese_number = match.group(1)  # 提取數字部分
        return chinese_numbers.get(
            chinese_number, -1
        )  # 返回對應的數字，如果找不到則返回 None
    return -1


# 函数：将数字转换为 "第xx屆" 形式的中文
def number_to_chinese(num):
    # 先检查数字是否在字典中
    for chinese_str, number in chinese_numbers.items():
        if num == number:
            return f"第{chinese_str}屆"
    return f"第{num}屆"  # 如果没有找到，则返回默认格式


def custom_secure_filename(filename):
    # 保留中文、英文、數字、底線、括號、點、減號
    filename = re.sub(r"[^\w\u4e00-\u9fa5().-]", "_", filename)
    return filename


def generate_unique_filename(original_filename):
    base, ext = original_filename.rsplit(".", 1)
    base = custom_secure_filename(base)
    ext = custom_secure_filename(ext)
    safe_name = f"{base}.{ext}"

    # 檢查資料庫中是否存在
    existing = File.query.filter_by(original_filename=safe_name).first()
    if existing:
        timestamp = int(time.time())
        safe_name = f"{base}_{timestamp}.{ext}"

    return safe_name


def convert_to_dict(data):
    result = {}
    for item in data:
        role = item["role"]
        members = item["members"]
        result[role] = members
    return result


def addSchedule(content, id, type):
    st_time = time.time()
    for schedule in content:
        if type == "notification":
            schedule_obj = Schedule(
                title=schedule["title"],
                notification_id=id,
            )
        else:
            schedule_obj = Schedule(
                title=schedule["title"],
                record_id=id,
            )
        db.session.add(schedule_obj)
        db.session.flush()
        for detail in schedule["details"]:
            detail_obj = Detail(
                content=detail["content"],
                schedule_id=schedule_obj.id,
            )
            db.session.add(detail_obj)
            db.session.flush()

            for file_item in detail.get("file_urls", []):
                # 檢查這個檔案是否已存在
                existing_file = File.query.filter_by(
                    filename_with_timestamp=file_item["safe"]
                ).first()

                if existing_file:
                    file_obj = existing_file  # 直接使用舊的 File 資料
                else:
                    file_obj = File(
                        original_filename=file_item["original"],
                        filename_with_timestamp=file_item["safe"],
                    )
                    db.session.add(file_obj)
                    db.session.flush()  # 確保 file.id 可用
                db.session.execute(
                    detail_file.insert().values(
                        detail_id=detail_obj.id, file_id=file_obj.id
                    )
                )
    db.session.commit()
    print("add", id, type, time.time() - st_time)


def deletSchedule(id, deleted_files, type):
    st_time = time.time()
    if type == "notification":
        old_schedules = Schedule.query.filter(Schedule.notification_id == id).all()
    else:
        old_schedules = Schedule.query.filter(Schedule.record_id == id).all()
    for sched in old_schedules:
        dele_time = time.time()
        if deleted_files:
            for detail in sched.details:
                for file in detail.files:
                    if (
                        len(file.details) == 1
                        and file.filename_with_timestamp in deleted_files
                    ):
                        try:
                            s3_time = time.time()
                            s3.delete_object(
                                Bucket=S3_BUCKET, Key=file.filename_with_timestamp
                            )
                            print(
                                "s3",
                                file.filename_with_timestamp,
                                time.time() - s3_time,
                            )
                        except Exception as e:
                            print("刪除 S3 失敗：", e)
                        db.session.delete(file)  # 刪掉資料庫中的 File 資料
            print("全部刪檔案", time.time() - dele_time)
        db.session.delete(sched)
    db.session.commit()
    print("delete", id, type, time.time() - st_time)


# 設定如何載入使用者
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/")
def index():
    logout_user()
    session.clear()
    return render_template("index.html")  # 登录页面


# 登录页面
@app.route("/login", methods=["POST"])
def login():
    if request.method == "POST":
        # session.pop("logged_in", None)  # 访问 login 页面时自动登出
        data = request.get_json()
        username = data.get("username")
        password = data.get("password")
        # 假設這裡直接從資料庫查詢使用者
        user = User.query.filter_by(username=username).first()
        if user and user.password == password:  # 驗證密碼
            login_user(user)  # 登入使用者
            print("帳密正確")
            return jsonify({"success": True}), 200  # 登入後重定向到 admin 頁面
        else:
            print("帳密錯誤")
            return (
                jsonify({"success": False, "message": "Invalid credentials"}),
                401,
            )  # 錯誤的帳號或密碼
    return render_template("index.html")


# 登出路由
@app.route("/logout", methods=["GET"])
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin")
# @login_required  # 需要用戶登入才能訪問
def admin_page():
    return render_template("admin.html")


@app.route("/admin/data")
# @login_required  # 需要用戶登入才能訪問
def admin_data():
    try:
        notifications = (
            db.session.query(Notification)
            .order_by(Notification.session.desc(), Notification.date.desc())
            .all()
        )
        result = []
        session_list = []
        for notification in notifications:
            tmpSession = number_to_chinese(notification.session)
            if tmpSession not in session_list:
                session_list.append(tmpSession)
            notification_data = {
                "id": notification.id,
                "title": notification.title,
                "session": tmpSession,
            }
            result.append(notification_data)
        return jsonify({"notifications": result, "session_list": session_list}), 200
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/admin/data/<int:id>", methods=["GET"])
# @login_required  # 需要用戶登入才能訪問
def admin_getdetail(id):
    try:
        notification = db.session.query(Notification).get(id)
        if notification:
            result = []
            tmpSession = number_to_chinese(notification.session)
            notification_data = {
                "id": notification.id,
                "title": notification.title,
                "session": tmpSession,
                "place": notification.place,
                "date": notification.date,
                "person": notification.person,
                "shorthand": notification.shorthand,
                "attendance": notification.attendance,
                "present": notification.present,
                "is_visible": notification.is_visible,
            }

            # 預先載入每個 schedule 的 details 和每個 detail 的 files
            schedules = (
                Schedule.query.filter_by(notification_id=notification.id)
                .options(joinedload(Schedule.details).joinedload(Detail.files))
                .all()
            )
            schedule_data = []
            file_url_tmp = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/"
            for schedule in schedules:
                detail_data = []
                for detail in schedule.details:
                    file_name = []
                    file_url = []

                    for file in detail.files:
                        file_name.append(file.original_filename)
                        file_url.append(file_url_tmp + file.filename_with_timestamp)

                    detail_data.append(
                        {
                            "id": detail.id,
                            "content": detail.content,
                            "file_name": file_name,
                            "file_urls": file_url,
                        }
                    )
                schedule_data.append(
                    {
                        "id": schedule.id,
                        "title": schedule.title,
                        "details": detail_data,
                    }
                )
            # 將整理好的 schedule_data 放進 notification_data 裡
            notification_data["schedules"] = schedule_data
            result.append(notification_data)
            return jsonify({"notifications": result}), 200
        else:
            return jsonify({"error": "找不到此通知"}), 500
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/newRecord", methods=["POST"])
def upload_record():
    try:
        # 基本欄位
        data = {
            "title": request.form.get("title"),
            "session": chinese_to_number(request.form.get("session")),
            "date": datetime.fromisoformat(request.form.get("date")),
            "place": request.form.get("place"),
            "person": request.form.get("person"),
            "shorthand": request.form.get("shorthand"),
        }

        present_json = request.form.get("present")
        attendance_json = request.form.get("attendance")
        present_dict = json.loads(present_json)
        attendance_dict = json.loads(attendance_json)
        data["present"] = present_dict
        data["attendance"] = attendance_dict
        # content_json = request.form.get("content")
        # content = json.loads(content_json)
        # uploaded_files_info = {}

        # # 上傳檔案
        # for key in request.files:
        #     if key.startswith("newfile-"):
        #         file = request.files[key]
        #         original_filename = file.filename
        #         safe_filename = generate_unique_filename(original_filename)

        #         s3.upload_fileobj(
        #             file, S3_BUCKET, safe_filename, ExtraArgs={"ACL": "public-read"}
        #         )
        #         uploaded_files_info[original_filename] = {
        #             "original": original_filename,
        #             "safe": safe_filename,
        #         }

        # # 填入 file_urls
        # for schedule in content:
        #     for detail in schedule["details"]:
        #         detail["file_urls"] = []

        #         file_dict_urls = [
        #             {"original": file["name"], "safe": file["url"]}
        #             for file in detail.get("file_dict", [])
        #         ]
        #         # 再處理 files
        #         if "fileName" in detail:
        #             for fname in detail["fileName"]:
        #                 if fname in uploaded_files_info:
        #                     detail["file_urls"].append(uploaded_files_info[fname])

        #         detail["file_urls"] = file_dict_urls + detail["file_urls"]

        # data["content"] = content
        # id = request.form.get("id")

        # if id != "-1":
        #     # 修改舊資料
        #     print("修改通知id = ", id, " 修改舊資料")
        #     existing_notification = Notification.query.get(id)
        #     if not existing_notification:
        #         return {"error": "找不到通知資料"}, 404

        #     # 更新 Notification 欄位
        #     existing_notification.title = data["title"]
        #     existing_notification.session = data["session"]
        #     existing_notification.date = data["date"]
        #     existing_notification.place = data["place"]
        #     existing_notification.person = data["person"]
        #     existing_notification.shorthand = data["shorthand"]
        #     existing_notification.present = data["present"]
        #     existing_notification.attendance = data["attendance"]
        #     db.session.commit()

        #     # 刪除 Notification 對應的所有 Schedule（自動 cascade 刪除 detail & file）
        #     old_notif_schedules = Schedule.query.filter_by(
        #         notification_id=existing_notification.id
        #     ).all()
        #     for sched in old_notif_schedules:
        #         db.session.delete(sched)
        #     db.session.commit()

        #     # 重新建立新的 schedule 和 detail
        #     for schedule in content:
        #         notif_schedule = Schedule(
        #             title=schedule["title"],
        #             notification_id=existing_notification.id,
        #         )
        #         db.session.add(notif_schedule)
        #         db.session.flush()

        #         # 假設你已經有 notif_schedule 了
        #         for detail in schedule["details"]:
        #             notif_detail = Detail(
        #                 content=detail["content"],
        #                 schedule_id=notif_schedule.id,
        #             )
        #             db.session.add(notif_detail)
        #             db.session.flush()  # 確保 detail_obj.id 可用

        #             for file_item in detail.get("file_urls", []):
        #                 file_obj = File(
        #                     original_filename=file_item["original"],
        #                     filename_with_timestamp=file_item["safe"],
        #                     detail_id=notif_detail.id,
        #                 )
        #                 db.session.add(file_obj)
        #         db.session.commit()
        # else:
        #     print("通知id = ", id, " 新增資料")
        #     # 新增資料
        #     new_notification = Notification(
        #         title=data["title"],
        #         session=data["session"],
        #         date=data["date"],
        #         place=data["place"],
        #         person=data["person"],
        #         shorthand=data["shorthand"],
        #         present=data["present"],
        #         attendance=data["attendance"],
        #         user_id=current_user.id,
        #     )
        #     db.session.add(new_notification)
        #     db.session.commit()

        #     for schedule in content:
        #         notif_schedule = Schedule(
        #             title=schedule["title"],
        #             notification_id=new_notification.id,
        #         )
        #         db.session.add(notif_schedule)
        #         db.session.flush()

        #         # 假設你已經有 notif_schedule 了
        #         for detail in schedule["details"]:
        #             notif_detail = Detail(
        #                 content=detail["content"],
        #                 schedule_id=notif_schedule.id,
        #             )
        #             db.session.add(notif_detail)
        #             db.session.flush()  # 確保 detail_obj.id 可用

        #             for file_item in detail.get("file_urls", []):
        #                 file_obj = File(
        #                     original_filename=file_item["original"],
        #                     filename_with_timestamp=file_item["safe"],
        #                     detail_id=notif_detail.id,
        #                 )
        #                 db.session.add(file_obj)
        #         db.session.commit()
        return admin_data()
    except Exception as e:
        db.session.rollback()
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/newNotification", methods=["POST"])
def upload_notifi():
    try:
        not_time = time.time()
        # 基本欄位
        is_visible = request.form.get("is_visible")
        data = {
            "title": request.form.get("title"),
            "session": chinese_to_number(request.form.get("session")),
            "date": datetime.fromisoformat(request.form.get("date")),
            "place": request.form.get("place"),
            "person": request.form.get("person"),
            "shorthand": request.form.get("shorthand"),
            "is_visible": True if is_visible == "true" else False,
        }

        present_json = request.form.get("present")
        attendance_json = request.form.get("attendance")
        present_dict = json.loads(present_json)
        attendance_dict = json.loads(attendance_json)
        data["present"] = present_dict
        data["attendance"] = attendance_dict

        content_json = request.form.get("content")
        content = json.loads(content_json)
        uploaded_files_info = {}
        # 上傳檔案
        for key in request.files:
            upload_time = time.time()
            if key.startswith("newfile-"):
                file = request.files[key]
                original_filename = file.filename
                safe_filename = generate_unique_filename(original_filename)

                s3.upload_fileobj(
                    file, S3_BUCKET, safe_filename, ExtraArgs={"ACL": "public-read"}
                )
                uploaded_files_info[original_filename] = {
                    "original": original_filename,
                    "safe": safe_filename,
                }
            print(original_filename, "上傳s3", time.time() - upload_time)
        deleted_files = []
        # 填入 file_urls
        for schedule in content:
            for detail in schedule["details"]:
                if detail.get(
                    "deleted_files"
                ):  # 假設使用 deleted_files 儲存被刪除的檔案
                    deleted_files += detail.get("deleted_files")
                detail["file_urls"] = []

                file_dict_urls = [
                    {"original": file["name"], "safe": file["url"]}
                    for file in detail.get("file_dict", [])
                ]
                # 再處理 files
                if "fileName" in detail:
                    for fname in detail["fileName"]:
                        if fname in uploaded_files_info:
                            detail["file_urls"].append(uploaded_files_info[fname])

                detail["file_urls"] = file_dict_urls + detail["file_urls"]
        id = request.form.get("id")
        if id == "-1":
            print("通知id = ", id, " 新增資料")
            # 新增資料
            new_notification = Notification(
                title=data["title"],
                session=data["session"],
                date=data["date"],
                place=data["place"],
                person=data["person"],
                shorthand=data["shorthand"],
                present=data["present"],
                attendance=data["attendance"],
                is_visible=data["is_visible"],
                user_id=current_user.id,
            )
            db.session.add(new_notification)

            if data["is_visible"]:
                new_record = Record(
                    title=data["title"],
                    session=data["session"],
                    date=data["date"],
                    place=data["place"],
                    person=data["person"],
                    shorthand=data["shorthand"],
                    present=data["present"],
                    attendance=data["attendance"],
                    is_visible=False,
                    is_modify=False,
                    user_id=current_user.id,
                )
                db.session.add(new_record)
                db.session.flush()

                new_notification.record_id = new_record.id
                addSchedule(content, new_record.id, "record")
            addSchedule(content, new_notification.id, "notification")
            db.session.commit()
        else:
            # 修改舊資料
            print("修改通知id = ", id, " 修改舊資料", "time", time.time())
            existing_notification = Notification.query.get(id)
            if not existing_notification:
                return {"error": "找不到通知資料"}, 404

            # 更新 Notification 欄位
            existing_notification.title = data["title"]
            existing_notification.session = data["session"]
            existing_notification.date = data["date"]
            existing_notification.place = data["place"]
            existing_notification.person = data["person"]
            existing_notification.shorthand = data["shorthand"]
            existing_notification.present = data["present"]
            existing_notification.attendance = data["attendance"]
            existing_notification.is_visible = data["is_visible"]
            record_id = existing_notification.record_id
            db.session.flush()
            if record_id:
                existing_record = Record.query.get(record_id)
                if not existing_record.is_modify:  # 此紀錄還沒被更改
                    existing_record.title = data["title"]
                    existing_record.session = data["session"]
                    existing_record.date = data["date"]
                    existing_record.place = data["place"]
                    existing_record.person = data["person"]
                    existing_record.shorthand = data["shorthand"]
                    existing_record.present = data["present"]
                    existing_record.attendance = data["attendance"]
                    db.session.flush()

                    deletSchedule(existing_record.id, deleted_files, "record")
                    addSchedule(content, existing_record.id, "record")
            else:
                if data["is_visible"]:
                    # 沒綁過且要上架
                    new_record = Record(
                        title=data["title"],
                        session=data["session"],
                        date=data["date"],
                        place=data["place"],
                        person=data["person"],
                        shorthand=data["shorthand"],
                        present=data["present"],
                        attendance=data["attendance"],
                        is_visible=False,
                        is_modify=False,
                        user_id=current_user.id,
                    )
                    db.session.add(new_record)
                    db.session.flush()
                    existing_notification.record_id = new_record.id
                    addSchedule(content, new_record.id, "record")
            db.session.commit()
            deletSchedule(existing_notification.id, deleted_files, "notification")
            # 重新建立新的 schedule 和 detail
            addSchedule(content, existing_notification.id, "notification")
        print("完成", time.time() - not_time)
        return admin_data()
    except Exception as e:
        db.session.rollback()
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/admin/minutes")
# @login_required  # 需要用戶登入才能訪問
def admin_minutes_page():

    return render_template("admin_minutes.html")


@app.route("/admin/regulations")
# @login_required  # 需要用戶登入才能訪問
def admin_regulations_page():

    return render_template("admin_regulations.html")


@app.route("/admin/article/<int:article_id>", methods=["GET", "POST"])
# @login_required  # 需要登录才能访问
def admin_check_article(article_id):
    # 管理员检查文章
    pass


@app.route("/article/<int:article_id>", methods=["GET"])
def view_article(article_id):
    # 展示文章内容给浏览者
    pass


if __name__ == "__main__":
    # app.run(debug=True)
    # app.run(host="0.0.0.0", port="8012", debug=True)
    debug_mode = os.getenv("FLASK_ENV") != "production"
    app.run(debug=debug_mode, port=8012)  # 預設啟動在 localhost:5000
