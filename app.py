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
from sqlalchemy import text
from dotenv import load_dotenv

# 載入本地 .env 環境變數
load_dotenv()

app = Flask(__name__)

# Flask-Login 配置
app.secret_key = "your_secret_key"  # 用于加密会话
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"  # 未登入時會重定向到 login 頁面


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
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

    # 一個用戶可以擁有多條通知和紀錄
    notifications = db.relationship("Notification", backref="user", lazy=True)
    records = db.relationship("Record", backref="user", lazy=True)

    def __repr__(self):
        return f"<User {self.username}>"


# 用户示例数据
class User_test(UserMixin):
    def __init__(self, id):
        self.id = id


# 通知資料表
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    session = db.Column(db.String(100), nullable=False)
    date = db.Column(db.Date, nullable=False)
    place = db.Column(db.String(100), nullable=False)
    person = db.Column(db.String(100), nullable=True)
    shorthand = db.Column(db.String(100), nullable=True)
    attendance = db.Column(db.String(100), nullable=True)
    present = db.Column(db.String(100), nullable=True)
    # 外鍵連接到用戶
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    # 外鍵連接到多個排程
    schedules = db.relationship("Schedule", backref="notification", lazy=True)

    def __repr__(self):
        return f"<Notification {self.title}>"


# 紀錄資料表
class Record(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    session = db.Column(db.String(100), nullable=False)
    date = db.Column(db.Date, nullable=False)
    place = db.Column(db.String(100), nullable=False)
    person = db.Column(db.String(100), nullable=True)
    shorthand = db.Column(db.String(100), nullable=True)
    attendance = db.Column(db.String(100), nullable=True)
    present = db.Column(db.String(100), nullable=True)

    # 外鍵連接到用戶
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    # 外鍵連接到多個排程
    schedules = db.relationship("Schedule", backref="record", lazy=True)

    def __repr__(self):
        return f"<Record {self.title}>"


# 排程資料表
class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    date = db.Column(db.Date, nullable=False)
    content = db.Column(db.Text, nullable=True)
    type = db.Column(db.String(20), nullable=False)  # 'notification' 或 'record'
    is_modified = db.Column(db.Boolean, default=False)  # 只有 record 會有此欄位
    notification_id = db.Column(
        db.Integer, db.ForeignKey("notification.id"), nullable=True
    )
    record_id = db.Column(db.Integer, db.ForeignKey("record.id"), nullable=True)

    # 外鍵連接到 Detail
    details = db.relationship("Detail", backref="schedule", lazy=True)

    def __repr__(self):
        return f"<Schedule {self.title}>"


# 排程細項資料表
class Detail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=True)
    file_urls = db.Column(db.JSON, nullable=True, default=[])  # 儲存檔案URL的列表

    schedule_id = db.Column(db.Integer, db.ForeignKey("schedule.id"), nullable=False)

    def __repr__(self):
        return f"<Detail {self.id}>"


# 創建資料庫表格
with app.app_context():
    db.create_all()

# 模拟的用户数据存储（通常应该是数据库）
users = {"123": {"password": "123"}}
scsession = ["第二十三屆", "第二十四屆", "第二十五屆"]
record = [
    {
        # "第二十三屆": [
        #     {
        #         "title": "第二十三屆第2次常會會議通知",
        #         "description": "This is item 1",
        #     }
        # ],
        # "第二十四屆": [
        #     {
        #         "title": "第二十四屆第6次常會會議通知",
        #         "description": "This is item 2",
        #     },
        #     {
        #         "title": "第二十四屆第7次常會會議通知",
        #         "description": "This is item 2",
        #     },
        # ],
        # "第二十五屆": [
        #     {
        #         "id": 6,
        #         "name": "第二十五屆",
        #         "title": "第二十五屆第6次常會會議通知",
        #         "description": "This is item 3",
        #     },
        #     {
        #         "id": 7,
        #         "name": "第二十五屆",
        #         "title": "第二十五屆第7次常會會議通知",
        #         "description": "This is item 3",
        #     },
        #     {
        #         "id": 8,
        #         "name": "第二十五屆",
        #         "title": "第二十五屆第6次常會會議通知",
        #         "description": "This is item 3",
        #     },
        # ],
        "第二十六屆": [
            {
                "id": 6,
                "name": "第二十五屆",
                "title": "第二十五屆第6次常會會議通知",
                "description": "This is item 3",
            },
            {
                "id": 7,
                "name": "第二十五屆",
                "title": "第二十五屆第7次常會會議通知",
                "description": "This is item 3",
            },
            {
                "id": 2,
                "name": "第二十五屆",
                "title": "第二十五屆第7次常會會議通知",
                "description": "This is item 3",
            },
            {
                "id": 4,
                "name": "第二十五屆",
                "title": "第二十五屆第7次常會會議通知",
                "description": "This is item 3",
            },
        ],
    }
]


# 設定如何載入使用者
@login_manager.user_loader
def load_user(user_id):
    if user_id in users:
        return User_test(user_id)
    return None


@app.route("/")
def index():
    return render_template("index.html")  # 登录页面


# 登录页面
@app.route("/login", methods=["POST"])
def login():
    if request.method == "POST":
        # session.pop("logged_in", None)  # 访问 login 页面时自动登出
        data = request.get_json()
        username = data.get("username")
        password = data.get("password")
        # 验证账号密码
        if username in users and users[username]["password"] == password:
            session["logged_in"] = True  # 记录登录状态
            user = User_test(username)  # 創建 User 物件，根據自己的需求進行實現
            login_user(user)  # 登入用戶
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "message": "Invalid credentials"}), 401
    # # 登录失败，返回错误信息
    return render_template("index.html")


# 登出路由
@app.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()  # 清除 Session
    print("logout")
    return redirect(url_for("index"))


@app.route("/admin")
@login_required  # 需要用戶登入才能訪問
def admin_page():
    print("login")
    # if not session.get("logged_in"):  # 检查用户是否已登录
    #     return redirect(url_for("index"))  # 未登录，跳转到登录页
    print(current_user.id)
    return render_template("admin.html")


@app.route("/admin/data")
@login_required  # 需要用戶登入才能訪問
def admin_data():
    flipped_record = dict(reversed(record[0].items()))
    # print(flipped_record)
    return json.dumps([flipped_record])


@app.route("/newRecord", methods=["POST"])
@login_required  # 需要用戶登入才能訪問
def upload_record():
    try:
        # 基本欄位
        data = {
            "title": request.form.get("title"),
            "session": request.form.get("session"),
            "date": request.form.get("date"),
            "place": request.form.get("place"),
            "person": request.form.get("person"),
            "shorthand": request.form.get("shorthand"),
        }

        present_json = request.form.get("present")
        attendance_json = request.form.get("attendance")
        print(present_json)
        # 將 JSON 字符串轉換為 Python 字典
        present_dict = json.loads(present_json)
        attendance_dict = json.loads(attendance_json)
        data["present"] = present_dict
        data["attendance"] = attendance_dict

        # 解析 content JSON
        content_json = request.form.get("content")
        content = json.loads(content_json)

        uploaded_files_info = {}

        for key in request.files:
            if key.startswith("file_"):
                file = request.files[key]
                file_name = file.filename

                # 上傳到 S3
                s3.upload_fileobj(
                    file, S3_BUCKET, file_name, ExtraArgs={"ACL": "public-read"}
                )
                file_url = (
                    f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{file_name}"
                )
                uploaded_files_info[key] = file_url

        # 回填 file_url 到 content 結構
        for schedule in content:
            for detail in schedule["details"]:
                if "files" in detail:
                    detail["file_urls"] = []
                    for fname in detail["files"]:
                        if fname in uploaded_files_info:
                            detail["file_urls"].append(uploaded_files_info[fname])

        data["content"] = content

        # 你可以存進資料庫、session 或是寫檔
        # updated_session = {data["session"]: data}
        if data["session"] not in record[0]:
            record[0][data["session"]] = []

        record[0][data["session"]].append(data)
        flipped_record = dict(reversed(record[0].items()))
        print(flipped_record)
        return jsonify({"message": "儲存成功", "updatedData": flipped_record})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/minutes")
@login_required  # 需要用戶登入才能訪問
def admin_minutes_page():
    try:
        result = db.session.execute(text("SELECT NOW()"))
        current_time = result.scalar()
        return f"✅ 資料庫連線成功，目前時間：{current_time}"
    except Exception as e:
        return f"❌ 資料庫連線失敗：{str(e)}"
    # return render_template("admin_minutes.html")


@app.route("/admin/regulations")
@login_required  # 需要用戶登入才能訪問
def admin_regulations_page():

    return render_template("admin_regulations.html")


@app.route("/admin/article/<int:article_id>", methods=["GET", "POST"])
@login_required  # 需要登录才能访问
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
