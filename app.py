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

# 假设文章存储在字典中
articles = {}
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# 用户示例数据
class User(UserMixin):
    def __init__(self, id):
        self.id = id


# 模拟的用户数据存储（通常应该是数据库）
users = {"123": {"password": "123"}}
scsession = ["第二十三屆", "第二十四屆", "第二十五屆"]
record = [
    {
        "第二十三屆": [
            {
                "title": "第二十三屆第2次常會會議紀錄",
                "description": "This is item 1",
            }
        ],
        "第二十四屆": [
            {
                "title": "第二十四屆第6次常會會議紀錄",
                "description": "This is item 2",
            },
            {
                "title": "第二十四屆第7次常會會議紀錄",
                "description": "This is item 2",
            },
        ],
        "第二十五屆": [
            {
                "id": 6,
                "name": "第二十五屆",
                "title": "第二十五屆第6次常會會議紀錄",
                "description": "This is item 3",
            },
            {
                "id": 7,
                "name": "第二十五屆",
                "title": "第二十五屆第7次常會會議紀錄",
                "description": "This is item 3",
            },
            {
                "id": 8,
                "name": "第二十五屆",
                "title": "第二十五屆第6次常會會議紀錄",
                "description": "This is item 3",
            },
        ],
        "第二十六屆": [
            {
                "id": 6,
                "name": "第二十五屆",
                "title": "第二十五屆第6次常會會議紀錄",
                "description": "This is item 3",
            },
            {
                "id": 7,
                "name": "第二十五屆",
                "title": "第二十五屆第7次常會會議紀錄",
                "description": "This is item 3",
            },
            {
                "id": 2,
                "name": "第二十五屆",
                "title": "第二十五屆第7次常會會議紀錄",
                "description": "This is item 3",
            },
            {
                "id": 4,
                "name": "第二十五屆",
                "title": "第二十五屆第7次常會會議紀錄",
                "description": "This is item 3",
            },
        ],
    }
]


# 設定如何載入使用者
@login_manager.user_loader
def load_user(user_id):
    if user_id in users:
        return User(user_id)
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
            user = User(username)  # 創建 User 物件，根據自己的需求進行實現
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
def newRecord():
    data = request.get_json()
    # print(data)
    if data["session"] not in record[0]:
        record[0][data["session"]] = []
    # tmp = {
    #     "title": data["title"],
    #     "description": data["content"],
    # }
    record[0][data["session"]].append(data)
    flipped_record = dict(reversed(record[0].items()))
    print(flipped_record)
    return json.dumps([flipped_record])


# **📌 上傳 API**
@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "請上傳檔案"}), 400

    file = request.files["file"]
    file_name = file.filename

    # **上傳並設為「public-read」**
    s3.upload_fileobj(file, S3_BUCKET, file_name, ExtraArgs={"ACL": "public-read"})

    # **產生公開 URL**
    file_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{file_name}"

    return jsonify({"message": "檔案上傳成功", "file_url": file_url})


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
    app.run(host="0.0.0.0", port="8012", debug=True)
