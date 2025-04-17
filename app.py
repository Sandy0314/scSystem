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
from sqlalchemy.orm import joinedload
from dotenv import load_dotenv
from datetime import datetime
import re, time

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
# with app.app_context():
#     db.create_all()


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


def getAllMeetTitleFromDB(Table):
    tables = (
        db.session.query(Table).order_by(Table.session.desc(), Table.date.desc()).all()
    )
    result = []
    seen_sessions = set()
    session_list = []
    for table in tables:
        session_str = number_to_chinese(table.session)
        if session_str not in seen_sessions:
            seen_sessions.add(session_str)
            session_list.append(session_str)

        result.append(
            {
                "id": table.id,
                "title": table.title,
                "session": session_str,
            }
        )
    return result, session_list


def serialize_schedule(schedule):
    return {
        "id": schedule.id,
        "title": schedule.title,
        "details": [serialize_detail(detail) for detail in schedule.details],
    }


def serialize_detail(detail):
    file_url_base = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/"
    return {
        "id": detail.id,
        "content": detail.content,
        "file_name": [f.original_filename for f in detail.files],
        "file_urls": [file_url_base + f.filename_with_timestamp for f in detail.files],
    }


def getMeetContentFromDB(Table, id, is_record):
    table = db.session.query(Table).get(id)
    if not table:
        return []

    result = []
    table_data = {
        "id": table.id,
        "title": table.title,
        "session": number_to_chinese(table.session),
        "place": table.place,
        "date": table.date,
        "person": table.person,
        "shorthand": table.shorthand,
        "attendance": table.attendance,
        "present": table.present,
        "is_visible": table.is_visible,
    }

    # 預先載入每個 schedule 的 details 和每個 detail 的 files
    filter_kwargs = (
        {"record_id": table.id} if is_record else {"notification_id": table.id}
    )
    schedules = (
        Schedule.query.filter_by(**filter_kwargs)
        .options(joinedload(Schedule.details).joinedload(Detail.files))
        .all()
    )

    table_data["schedules"] = [serialize_schedule(sched) for sched in schedules]
    result.append(table_data)
    return result


def parse_json_field(request, field_name):
    try:
        return json.loads(request.form.get(field_name, "{}"))
    except json.JSONDecodeError:
        print(f"JSON decode error for field: {field_name}")
        return {}


def getDataFromFrontend(request):
    is_visible = request.form.get("is_visible")
    data = {
        "title": request.form.get("title"),
        "session": chinese_to_number(request.form.get("session")),
        "date": datetime.fromisoformat(request.form.get("date")),
        "place": request.form.get("place"),
        "person": request.form.get("person"),
        "shorthand": request.form.get("shorthand"),
        "is_visible": True if is_visible == "true" else False,
        "present": parse_json_field(request, "present"),
        "attendance": parse_json_field(request, "attendance"),
    }

    uploaded_files_info = {}
    # 上傳檔案
    for key in request.files:
        if key.startswith("newfile-"):
            file = request.files[key]
            original = file.filename
            safe = generate_unique_filename(original)
            upload_time = time.time()
            s3.upload_fileobj(file, S3_BUCKET, safe, ExtraArgs={"ACL": "public-read"})
            uploaded_files_info[original] = {
                "original": original,
                "safe": safe,
            }
        print(original, "上傳s3", time.time() - upload_time)

    deleted_files = []
    content = content = parse_json_field(request, "content")
    # 填入 file_urls
    for schedule in content:
        for detail in schedule["details"]:
            if detail.get("deleted_files"):  # 假設使用 deleted_files 儲存被刪除的檔案
                deleted_files += detail.get("deleted_files")
            detail["file_urls"] = []
            # 處理舊檔案
            file_dict_urls = [
                {"original": file["name"], "safe": file["url"]}
                for file in detail.get("file_dict", [])
            ]
            # 來自本次上傳的新檔案
            new_file_urls = [
                uploaded_files_info[fname]
                for fname in detail.get("fileName", [])
                if fname in uploaded_files_info
            ]
            detail["file_urls"] = file_dict_urls + new_file_urls
    data["content"] = content
    return data, deleted_files


def addSchedule(content, id, is_record):
    st_time = time.time()
    for schedule in content:
        # 動態決定欄位
        schedule_kwargs = {
            "title": schedule["title"],
            "notification_id": None if is_record else id,
            "record_id": id if is_record else None,
        }
        schedule_obj = Schedule(**schedule_kwargs)
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
                # 檢查是否已有此檔案
                file_obj = File.query.filter_by(
                    filename_with_timestamp=file_item["safe"]
                ).first()

                if not file_obj:
                    file_obj = File(
                        original_filename=file_item["original"],
                        filename_with_timestamp=file_item["safe"],
                    )
                    db.session.add(file_obj)
                    db.session.flush()

                db.session.execute(
                    detail_file.insert().values(
                        detail_id=detail_obj.id, file_id=file_obj.id
                    )
                )
    db.session.commit()
    print(
        "更新/新增議程 id = ",
        id,
        " 是否為紀錄:",
        is_record,
        " 花費時間:",
        time.time() - st_time,
    )


def delete_file_if_unused(file, deleted_files_set):
    """
    如果檔案只被一個 detail 使用，且在刪除清單中，就從 S3 與資料庫中刪除。
    """
    if len(file.details) == 1 and file.filename_with_timestamp in deleted_files_set:
        try:
            s3_time = time.time()
            s3.delete_object(Bucket=S3_BUCKET, Key=file.filename_with_timestamp)
            print("s3", file.filename_with_timestamp, time.time() - s3_time)
        except Exception as e:
            print("刪除 S3 失敗：", e)
        db.session.delete(file)


def deletSchedule(id, deleted_files, is_record):
    st_time = time.time()
    schedule_filter = (
        Schedule.record_id == id if is_record else Schedule.notification_id == id
    )
    old_schedules = Schedule.query.filter(schedule_filter).all()

    for sched in old_schedules:
        dele_time = time.time()
        if deleted_files:
            for detail in sched.details:
                for file in detail.files:
                    delete_file_if_unused(file, deleted_files)
            print("全部刪檔案", time.time() - dele_time)
        db.session.delete(sched)
    db.session.commit()

    print("刪議程,id=", id, " 紀錄:", is_record, " 花費時間:", time.time() - st_time)


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


@app.route("/admin/notifi")
# @login_required  # 需要用戶登入才能訪問
def admin_notifi_page():
    return render_template("admin_notifi.html")


@app.route("/admin/notifi/data")
# @login_required  # 需要用戶登入才能訪問
def admin_notifi_data():
    try:
        result, session_list = getAllMeetTitleFromDB(Notification)
        return jsonify({"notifications": result, "session_list": session_list}), 200
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/admin/minutes/data")
# @login_required  # 需要用戶登入才能訪問
def admin_record_data():
    try:
        result, session_list = getAllMeetTitleFromDB(Record)
        return jsonify({"records": result, "session_list": session_list}), 200
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/admin/notifi/data/<int:id>", methods=["GET"])
# @login_required  # 需要用戶登入才能訪問
def admin_notifi_getdetail(id):
    try:
        result = getMeetContentFromDB(Notification, id, 0)
        if result:
            return jsonify({"notifications": result}), 200
        return jsonify({"error": "找不到此通知"}), 404
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/admin/minutes/data/<int:id>", methods=["GET"])
# @login_required  # 需要用戶登入才能訪問
def admin_record_getdetail(id):
    try:
        result = getMeetContentFromDB(Record, id, 1)
        if result:
            return jsonify({"records": result}), 200
        return jsonify({"error": "找不到此通知"}), 500
    except Exception as e:
        print("error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/newRecord", methods=["POST"])
def upload_record():
    try:
        record_time = time.time()
        data, deleted_files = getDataFromFrontend(request)
        record_id = request.form.get("id")

        is_new = record_id == "-1"
        if is_new:
            print("新增紀錄")
            record = Record(
                user_id=current_user.id,
                is_modify=True,
            )
            db.session.add(record)
        else:
            print(f"修改紀錄 id = {record_id}")
            record = Record.query.get(record_id)
            if not record:
                return {"error": "找不到紀錄資料"}, 404
            record.is_modify = True
        # 通用欄位填入
        for field in [
            "title",
            "session",
            "date",
            "place",
            "person",
            "shorthand",
            "present",
            "attendance",
            "is_visible",
        ]:
            setattr(record, field, data[field])
        db.session.flush()

        if not is_new:
            deletSchedule(record.id, deleted_files, is_record=True)

        addSchedule(data["content"], record.id, is_record=True)
        db.session.commit()
        print("完成", time.time() - record_time)

        return admin_record_data()
    except Exception as e:
        db.session.rollback()
        print(str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/newNotification", methods=["POST"])
def upload_notifi():
    try:
        not_time = time.time()
        data, deleted_files = getDataFromFrontend(request)

        noti_id = request.form.get("id")
        is_new = noti_id == "-1"

        # 建立或取得 Notification
        if is_new:
            print("新增通知")
            notification = Notification(user_id=current_user.id)
            db.session.add(notification)
        else:
            print(f"修改通知 id = {noti_id}")
            notification = Notification.query.get(noti_id)
            if not notification:
                return {"error": "找不到通知資料"}, 404
        # 通用欄位
        for field in [
            "title",
            "session",
            "date",
            "place",
            "person",
            "shorthand",
            "present",
            "attendance",
            "is_visible",
        ]:
            setattr(notification, field, data[field])
        db.session.flush()

        # 判斷是否要處理 Record（新增或同步更新）
        if data["is_visible"]:
            if is_new or not notification.record_id:
                # 沒有綁定，新增一筆 record
                record = Record(
                    user_id=current_user.id,
                    is_visible=False,
                    is_modify=False,
                )
                db.session.add(record)
                db.session.flush()
                notification.record_id = record.id
            else:
                # 如果 record 存在且尚未修改，同步更新內容
                record = Record.query.get(notification.record_id)
                if not record.is_modify:
                    db.session.flush()
            # 不論是新或更新，都補上欄位
            if not record.is_modify:
                for field in [
                    "title",
                    "session",
                    "date",
                    "place",
                    "person",
                    "shorthand",
                    "present",
                    "attendance",
                ]:
                    setattr(record, field, data[field])

                deletSchedule(record.id, deleted_files, is_record=True)
                addSchedule(data["content"], record.id, is_record=True)

        # 清空並重建通知的 schedule
        if not is_new:
            deletSchedule(notification.id, deleted_files, is_record=False)
        addSchedule(data["content"], notification.id, is_record=False)

        db.session.commit()
        print("完成", time.time() - not_time)
        return admin_notifi_data()
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
