from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from functools import wraps
import os
from werkzeug.utils import secure_filename
import threading
import time
import requests
import json
from urllib.parse import urlparse
from PIL import Image
import io

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///teams.db'
app.config['SECRET_KEY'] = 'your-secret-key-keep-it-safe'

# 配置文件上传
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 限制上传文件大小为16MB

# 确保上传目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 确保数据目录存在
DATA_FOLDER = 'static/data'
os.makedirs(DATA_FOLDER, exist_ok=True)

# 创建存储学校 logo 的目录
LOGO_FOLDER = 'static/logos'
os.makedirs(LOGO_FOLDER, exist_ok=True)

# 机器人数据文件路径
ROBOT_DATA_FILE = os.path.join(DATA_FOLDER, 'robot_data.json')
SCHEDULE_DATA_FILE = os.path.join(DATA_FOLDER, 'schedule.json')
REPLAY_DATA_FILE = os.path.join(DATA_FOLDER, 'simple_cms.json')
# 添加积分榜数据文件路径
GROUP_RANK_FILE = os.path.join(DATA_FOLDER, 'group_rank_info.json')

# 下载机器人数据的函数
def download_robot_data():
    try:
        # 从DJI API下载数据
        response = requests.get('https://rm-static.djicdn.com/live_json/robot_data.json', timeout=10)
        response.raise_for_status()  # 如果请求失败，抛出异常
        
        # 保存数据到本地文件
        with open(ROBOT_DATA_FILE, 'wb') as f:
            f.write(response.content)
        
        print(f"[{datetime.now()}] 成功下载机器人数据")

        # 从DJI API下载赛程数据
        schedule_response = requests.get('https://rm-static.djicdn.com/live_json/schedule.json', timeout=10)
        schedule_response.raise_for_status()  # 如果请求失败，抛出异常
        with open(SCHEDULE_DATA_FILE, 'wb') as f:
            f.write(schedule_response.content)
        print(f"[{datetime.now()}] 成功下载赛程数据")
        
        # 从DJI API下载回放数据
        replay_response = requests.get('https://rm-static.djicdn.com/live_json/simple_cms.json', timeout=10)
        replay_response.raise_for_status()
        with open(REPLAY_DATA_FILE, 'wb') as f:
            f.write(replay_response.content)
        print(f"[{datetime.now()}] 成功下载回放数据")
        
        # 添加积分榜数据下载
        rank_response = requests.get('https://rm-static.djicdn.com/live_json/group_rank_info.json', timeout=10)
        rank_response.raise_for_status()
        with open(GROUP_RANK_FILE, 'wb') as f:
            f.write(rank_response.content)
        print(f"[{datetime.now()}] 成功下载积分榜数据")
        
    except Exception as e:
        print(f"[{datetime.now()}] 下载数据失败: {str(e)}")

# 后台线程函数，定期下载数据
def background_downloader():
    # while True:
    #     download_robot_data()
    #     # 每10分钟执行一次
    #     time.sleep(600)
    pass

# 启动后台下载线程
download_thread = threading.Thread(target=background_downloader, daemon=True)
download_thread.start()

# 下载学校 logo 的函数
def download_school_logos():
    try:
        # 确保 robot_data.json 文件存在
        # if not os.path.exists(ROBOT_DATA_FILE):
        #     download_robot_data()
            
        # 读取 robot_data.json 文件
        with open(ROBOT_DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 记录所有学校的 logo URL
        logo_urls = {}
        for zone in data.get('zones', []):
            for team in zone.get('teams', []):
                college_name = team.get('collegeName', '')
                logo_url = team.get('collegeLogo', '')
                
                if college_name and logo_url:
                    logo_urls[college_name] = logo_url
        
        # 下载每个学校的 logo
        for college_name, logo_url in logo_urls.items():
            try:
                # 从 URL 解析文件扩展名
                parsed_url = urlparse(logo_url)
                path = parsed_url.path
                ext = os.path.splitext(path)[1]
                if not ext:
                    ext = '.jpg'  # 默认扩展名
                
                # 创建安全的文件名
                safe_name = ''.join(c if c.isalnum() or c in '_-' else '_' for c in college_name)
                filename = f"{safe_name}{ext}"
                filepath = os.path.join(LOGO_FOLDER, filename)
                
                # 如果文件不存在或已过期，则下载
                if not os.path.exists(filepath) or (time.time() - os.path.getmtime(filepath)) > 86400:
                    response = requests.get(logo_url, timeout=10)
                    response.raise_for_status()
                    
                    with open(filepath, 'wb') as f:
                        f.write(response.content)
                    
                    print(f"[{datetime.now()}] 成功下载 {college_name} 的 logo")
            except Exception as e:
                print(f"[{datetime.now()}] 下载 {college_name} 的 logo 失败: {str(e)}")
        
        print(f"[{datetime.now()}] 学校 logo 下载完成")
    except Exception as e:
        print(f"[{datetime.now()}] 下载学校 logo 失败: {str(e)}")

# 后台线程函数，定期下载学校 logo
def background_logo_downloader():
    while True:
        download_school_logos()
        # 每24小时执行一次
        time.sleep(86400)

# 启动下载学校 logo 的后台线程
logo_download_thread = threading.Thread(target=background_logo_downloader, daemon=True)
logo_download_thread.start()

db = SQLAlchemy(app)

# 登录密码 - 建议更改为强密码
try:
    LOGIN_PASSWORD = os.getenv('RMINTEL_LOGIN_PASSWORD')
except Exception as e:
    print(f"请在环境变量中设置密码")

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            flash('请先登录', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 数据库模型
class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    school = db.Column(db.String(100), nullable=False)
    team = db.Column(db.String(100), nullable=False)
    rank = db.Column(db.Integer, nullable=True)  # 队伍排名（可为空）
    # 考核排名
    rank_exam = db.Column(db.Integer, nullable=True)  # 考核排名（可为空）
    money = db.Column(db.Integer, nullable=True)  # 经济值（可为空）
    comment = db.Column(db.Text, nullable=True)  # 队伍备注（可为空）
    group = db.Column(db.String(10), default="A")  # 小组情况，默认为A组
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    def __repr__(self):
        return f'<Team {self.school} - {self.team}'

class TacticalData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    item = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

# 新增图片模型
class TeamImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    robot_type = db.Column(db.String(50), nullable=False)  # 机器人类型，如'步兵1'，'哨兵'等
    filename = db.Column(db.String(255), nullable=False)  # 存储的文件名
    description = db.Column(db.Text, nullable=True)  # 图片描述
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

# 32支预定义队伍（含排名）
PREDEFINED_TEAMS = [
    {"school": "演示大学", "team": "DEMO", "rank": 99, "rank_exam": 99, "money": -100},
    {"school": "北京科技大学", "team": "Reborn", "rank": 47, "rank_exam": 15, "money": 75},
    {"school": "北京理工大学", "team": "追梦", "rank": 28, "rank_exam": 91, "money": 50},
    {"school": "大连理工大学", "team": "凌BUG", "rank": 34, "rank_exam": 76, "money": -25},
    {"school": "东北大学", "team": "TDT", "rank": 3, "rank_exam": 5, "money": 0},
    {"school": "东华大学", "team": "DIODE", "rank": 111, "rank_exam": 95, "money": 25},
    {"school": "东南大学", "team": "3SE", "rank": 24, "rank_exam": 85, "money": -25},
    {"school": "哈尔滨工业大学（威海）", "team": "HERO", "rank": 22, "rank_exam": 25, "money": 100},
    {"school": "河北工业大学", "team": "山海机甲", "rank": 109, "rank_exam": 32, "money": -25},
    {"school": "华中科技大学", "team": "狼牙", "rank": 25, "rank_exam": 47, "money": -25},
    {"school": "吉林大学", "team": "TARS_Go", "rank": 31, "rank_exam": 37, "money": 0},
    {"school": "江苏大学", "team": "Aurora", "rank": 161, "rank_exam": 61, "money": -25},
    {"school": "辽宁科技大学", "team": "COD", "rank": 51, "rank_exam": 62, "money": 0},
    {"school": "南京航空航天大学", "team": "长空御风", "rank": 6, "rank_exam": 19, "money": 75},
    {"school": "南京理工大学", "team": "Alliance", "rank": 38, "rank_exam": 26, "money": 75},
    {"school": "宁波工程学院", "team": "New Legends", "rank": 146, "rank_exam": 70, "money": -75},
    {"school": "齐鲁工业大学", "team": "Adam", "rank": 42, "rank_exam": 67, "money": -25},
    {"school": "青岛大学", "team": "未来", "rank": 89, "rank_exam": 71, "money": 0},
    {"school": "山东科技大学", "team": "SmartRobot", "rank": 36, "rank_exam": 81, "money": -25},
    {"school": "山东理工大学", "team": "齐奇", "rank": 68, "rank_exam": 89, "money": 0},
    {"school": "上海工程技术大学", "team": "木鸢Birdiebot", "rank": 13, "rank_exam": 90, "money": -25},
    {"school": "上海科技大学", "team": "Magician", "rank": 66, "rank_exam": 84, "money": -25},
    {"school": "首都师范大学", "team": "PIE", "rank": 30, "rank_exam": 42, "money": -25},
    {"school": "太原工业学院", "team": "火线", "rank": 23, "rank_exam": 7, "money": 25},
    {"school": "天津大学", "team": "北洋机甲", "rank": 46, "rank_exam": 20, "money": 75},
    {"school": "同济大学", "team": "SuperPower", "rank": 68, "rank_exam": 13, "money": 175},
    {"school": "西安理工大学", "team": "NEXT E", "rank": 95, "rank_exam": 68, "money": 0},
    {"school": "燕山大学", "team": "燕鹰", "rank": 73, "rank_exam": 86, "money": 75},
    {"school": "浙江纺织服装职业技术学院", "team": "RoboFuture", "rank": 54, "rank_exam": 87, "money": 0},
    {"school": "浙江理工大学", "team": "钱塘蛟", "rank": 120, "rank_exam": 73, "money": 25},
    {"school": "中北大学", "team": "606", "rank": 64, "rank_exam": 34, "money": 50},
    {"school": "中国矿业大学", "team": "CUBOT", "rank": 44, "rank_exam": 40, "money": 0},
    {"school": "中国石油大学（北京）", "team": "SPR", "rank": 58, "rank_exam": 92, "money": 75},
]


# 战术数据分类
TACTICAL_CATEGORIES = [
    ('步兵1', ['构型','大小符','陡洞上', '陡洞下', '缓洞', '飞坡', '上台阶', '辅瞄', '初始弹量分配', '其他']),
    ('步兵2', ['构型','大小符','陡洞上', '陡洞下', '缓洞', '飞坡', '上台阶', '辅瞄', '初始弹量分配', '其他']),
    ('步兵(备用)', ['是否有', '构型','大小符','陡洞上', '陡洞下', '缓洞', '飞坡', '上台阶', '辅瞄', '初始弹量分配', '其他']),
    ('英雄', ['前哨站命中效率', '推前哨所需时间', '吊射点位1(缓洞口)', '吊射点位2(陡动口)', '吊射点位3(高地下)', '飞坡', '过洞', '初始弹量分配','其他']),
    ('英雄(备用)', ['是否有', '前哨站命中效率', '推前哨所需时间', '吊射点位1(缓洞口)', '吊射点位2(陡动口)', '吊射点位3(高地下)', '飞坡', '过洞', '初始弹量分配','其他']),
    ('工程', ['首矿时间', '局均经济', '开局抢矿策略', '捡地矿', '死亡是否掉矿', '挡拆策略', '其他']),
    ('工程(备用)', ['是否有', '首矿时间', '局均经济', '开局抢矿策略', '捡地矿', '死亡是否掉矿', '挡拆策略', '其他']),
    ('飞镖', ['目标', '命中率', '其他']),
    ('无人机', ['前哨站', '泼基地顶部', '泼基地底部', '地面', '其他']),
    ('哨兵', ['初始点位', '风格(前压or防守)', '巡航能力', '常见点位1', '常见点位2', '常见点位3', '堡垒', '地形跨越能力', '辅瞄', '对建筑能力', '其他']),
    ('雷达', ['易伤触发时间1', '易伤触发时间2', '明显盲区', '其他']),
]

# 梯队划分函数
def get_echelons(teams):
    """根据排名将队伍划分为四个梯队"""
    ranked_teams = [t for t in teams if t.rank_exam is not None]  # 过滤无排名队伍
    sorted_teams = sorted(ranked_teams, key=lambda x: x.rank_exam)  # 按排名排序
    
    return {
        'gold': sorted_teams[:4],       # 前4名
        'silver': sorted_teams[4:8],     # 5-8名
        'bronze': sorted_teams[8:16],    # 9-16名
        'iron': sorted_teams[16:32]      # 17-32名（最多32名）
    }

# 登录页面
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == LOGIN_PASSWORD:
            session['logged_in'] = True
            flash('登录成功', 'success')
            return redirect(url_for('index'))
        else:
            flash('密码错误', 'error')
    return render_template('login.html')

# 登出
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('已成功登出', 'success')
    return redirect(url_for('login'))

# 首页：显示队伍列表 + 梯队排名
@app.route('/')
@login_required
def index():
    teams = Team.query.all()
    echelons = get_echelons(teams)  # 获取梯队数据
    
    # 计算每个战队未更新的条目数
    team_update_stats = {}
    for team in teams:
        # 获取该队伍的所有战术数据
        tactical_data = TacticalData.query.filter_by(team_id=team.id).all()
        # 计算空内容（未更新）的条目数量
        empty_items = sum(1 for data in tactical_data if not data.content)
        team_update_stats[team.id] = empty_items
    
    return render_template('index.html', teams=teams, echelons=echelons, update_stats=team_update_stats)

# 添加队伍
@app.route('/add_team', methods=['GET', 'POST'])
@login_required
def add_team():
    if request.method == 'POST':
        school = request.form['school']
        team_name = request.form['team']
        rank = request.form.get('rank', type=int)  # 解析排名
        
        # 检查队伍是否存在
        if Team.query.filter_by(school=school, team=team_name).first():
            flash('队伍已存在', 'error')
            return redirect(url_for('add_team'))
        
        # 创建队伍
        new_team = Team(school=school, team=team_name, rank=rank)
        db.session.add(new_team)
        db.session.commit()
        
        # 初始化战术数据
        for category, items in TACTICAL_CATEGORIES:
            for item in items:
                data = TacticalData(
                    team_id=new_team.id,
                    category=category,
                    item=item,
                    content=''
                )
                db.session.add(data)
        db.session.commit()
        
        flash('队伍添加成功', 'success')
        return redirect(url_for('index'))
    
    return render_template('add_team.html', predefined_teams=PREDEFINED_TEAMS)

# 上传图片
@app.route('/upload_image/<int:team_id>', methods=['POST'])
@login_required
def upload_image(team_id):
    team = Team.query.get_or_404(team_id)
    
    # 检查是否有文件上传
    if 'image' not in request.files:
        flash('没有选择文件', 'error')
        return redirect(url_for('edit_team', id=team_id))
    
    file = request.files['image']
    if file.filename == '':
        flash('没有选择文件', 'error')
        return redirect(url_for('edit_team', id=team_id))
    
    robot_type = request.form.get('robot_type', '')
    description = request.form.get('description', '')
    
    if file and allowed_file(file.filename):
        try:
            # 获取安全的文件名基础部分
            original_filename = secure_filename(file.filename)
            filename_base = f"{int(datetime.now().timestamp())}_{os.path.splitext(original_filename)[0]}"
            
            # 打开图片并转换为RGB模式(如果是RGBA，移除透明通道)
            img = Image.open(file.stream)
            if img.mode == 'RGBA':
                img = img.convert('RGB')
                
            # 调整图片大小，如果太大的话
            max_size = (1200, 1200)  # 最大宽高
            if img.width > max_size[0] or img.height > max_size[1]:
                img.thumbnail(max_size, Image.LANCZOS)
            
            # 压缩并保存为jpg格式
            compressed_filename = f"{filename_base}.jpg"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], compressed_filename)
            
            # 使用较高的压缩率(质量较低的数值)来节省带宽
            img.save(filepath, 'JPEG', quality=65, optimize=True)
            
            # 保存到数据库
            image = TeamImage(
                team_id=team_id,
                robot_type=robot_type,
                filename=compressed_filename,
                description=description
            )
            db.session.add(image)
            db.session.commit()
            
            flash('图片上传成功', 'success')
        except Exception as e:
            print(f"图片处理失败: {str(e)}")
            flash('图片处理失败', 'error')
    else:
        flash('不支持的文件类型', 'error')
    
    return redirect(url_for('edit_team', id=team_id))

# 删除图片
@app.route('/delete_image/<int:image_id>', methods=['POST'])
@login_required
def delete_image(image_id):
    try:
        image = TeamImage.query.get_or_404(image_id)
        team_id = image.team_id
        
        # 保存文件名以便删除
        filename = image.filename
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # 从数据库中删除记录
        db.session.delete(image)
        db.session.commit()
        
        # 删除物理文件
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"成功删除文件: {file_path}")
            except Exception as e:
                print(f"删除文件错误: {e}")
        else:
            print(f"文件不存在: {file_path}")
        
        flash('图片已删除', 'success')
        return redirect(url_for('edit_team', id=team_id))
    
    except Exception as e:
        print(f"删除图片过程中发生错误: {e}")
        flash('删除图片失败，请重试', 'error')
        return redirect(url_for('index'))

# 查看队伍图片
@app.route('/team_images/<int:team_id>')
@login_required
def team_images(team_id):
    team = Team.query.get_or_404(team_id)
    images = TeamImage.query.filter_by(team_id=team_id).all()
    
    # 按机器人类型分组
    categorized_images = {}
    for category, _ in TACTICAL_CATEGORIES:
        categorized_images[category] = [img for img in images if img.robot_type == category]
    
    return render_template('team_images.html', team=team, images=categorized_images)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 修改编辑队伍的路由，添加小组字段处理
@app.route('/edit_team/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_team(id):
    team = Team.query.get_or_404(id)
    tactical_data = TacticalData.query.filter_by(team_id=id).all()
    
    # 获取队伍图片
    images = TeamImage.query.filter_by(team_id=id).all()
    categorized_images = {}
    for category, _ in TACTICAL_CATEGORIES:
        categorized_images[category] = [img for img in images if img.robot_type == category]
    
    # 按类别分组战术数据
    categorized_data = {}
    for category, _ in TACTICAL_CATEGORIES:
        categorized_data[category] = [d for d in tactical_data if d.category == category]
    
    if request.method == 'POST':
        # 检查是否是AJAX请求
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # 记录是否有任何更改
        has_changes = False
        
        # 检查并更新队伍基本信息 - 只更新有变化的字段
        if 'school' in request.form:
            new_school = request.form.get('school', '')
            if new_school and new_school != team.school:
                team.school = new_school
                has_changes = True
        
        if 'team' in request.form:
            new_team_name = request.form.get('team', '')
            if new_team_name and new_team_name != team.team:
                team.team = new_team_name
                has_changes = True
        
        if 'group' in request.form:
            new_group = request.form.get('group', '')
            if new_group and new_group != team.group:
                team.group = new_group
                has_changes = True
        
        # 安全地处理可能为空的整数字段
        if 'rank' in request.form:
            rank = request.form.get('rank', '')
            if rank.strip():  # 如果不是空字符串
                try:
                    new_rank = int(rank)
                    if team.rank != new_rank:
                        team.rank = new_rank
                        has_changes = True
                except ValueError:
                    pass  # 忽略无效输入
            elif team.rank is not None:  # 如果当前有值但表单为空
                team.rank = None
                has_changes = True
        
        if 'rank_exam' in request.form:
            rank_exam = request.form.get('rank_exam', '')
            if rank_exam.strip():
                try:
                    new_rank_exam = int(rank_exam)
                    if team.rank_exam != new_rank_exam:
                        team.rank_exam = new_rank_exam
                        has_changes = True
                except ValueError:
                    pass
            elif team.rank_exam is not None:
                team.rank_exam = None
                has_changes = True
        
        if 'money' in request.form:
            money = request.form.get('money', '')
            if money.strip():
                try:
                    new_money = int(money)
                    if team.money != new_money:
                        team.money = new_money
                        has_changes = True
                except ValueError:
                    pass
            elif team.money is not None:
                team.money = None
                has_changes = True
        
        if 'comment' in request.form:
            new_comment = request.form.get('comment', '')
            if new_comment != team.comment:
                team.comment = new_comment
                has_changes = True
        
        # 更新战术数据 - 只更新有变化的内容
        # 创建一个集合存储所有战术数据ID
        all_data_ids = {item.id for items in categorized_data.values() for item in items}
        
        # 处理提交的表单数据
        for key, value in request.form.items():
            # 检查是否是战术数据字段
            if key.startswith('content_'):
                try:
                    # 从字段名提取ID
                    data_id = int(key.replace('content_', ''))
                    
                    # 查找对应的战术数据项
                    for items in categorized_data.values():
                        for item in items:
                            if item.id == data_id:
                                # 检查内容是否有变化
                                if value != item.content:
                                    item.content = value
                                    item.updated_at = datetime.now(timezone.utc)
                                    has_changes = True
                                # 从集合中移除已处理的ID
                                all_data_ids.discard(data_id)
                                break
                except ValueError:
                    pass
        
        # 处理未提交但标记为未更改的字段 (前端标记为unchanged_content_xxx)
        for key in request.form.keys():
            if key.startswith('unchanged_content_'):
                try:
                    data_id = int(key.replace('unchanged_content_', ''))
                    # 从集合中移除这些未更改的ID
                    all_data_ids.discard(data_id)
                except ValueError:
                    pass
        
        # 未处理的ID表示这些字段在表单中没有提交也没有标记为未更改
        # 对于AJAX请求，这些字段保持不变；对于普通请求，重置为空
        if not is_ajax:
            for data_id in all_data_ids:
                for items in categorized_data.values():
                    for item in items:
                        if item.id == data_id and item.content:
                            item.content = ''
                            item.updated_at = datetime.now(timezone.utc)
                            has_changes = True
        
        # 只有当有变化时才更新队伍的更新时间并提交
        if has_changes:
            team.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            
            if is_ajax:
                return json.dumps({'message': '数据更新成功', 'redirect': url_for('view_team', id=id)})
            else:
                flash('数据更新成功', 'success')
        else:
            if is_ajax:
                return json.dumps({'message': '没有检测到数据变化', 'redirect': url_for('view_team', id=id)})
            else:
                flash('没有检测到数据变化', 'info')
        
        if not is_ajax:
            return redirect(url_for('view_team', id=id))
    
    return render_template('edit_team.html', team=team, data=categorized_data, images=categorized_images)

# 修改查看队伍的路由，添加图片数据
@app.route('/view_team/<int:id>')
@login_required
def view_team(id):
    team = Team.query.get_or_404(id)
    tactical_data = TacticalData.query.filter_by(team_id=id).all()
    
    # 获取队伍图片
    images = TeamImage.query.filter_by(team_id=id).all()
    categorized_images = {}
    for category, _ in TACTICAL_CATEGORIES:
        categorized_images[category] = [img for img in images if img.robot_type == category]
    
    # 按类别分组战术数据
    categorized_data = {}
    for category, _ in TACTICAL_CATEGORIES:
        categorized_data[category] = []
    
    for data in tactical_data:
        if data.category in categorized_data:
            categorized_data[data.category].append(data)
    
    return render_template('view_team.html', team=team, data=categorized_data, images=categorized_images)

# 查看队伍赛程
@app.route('/team_schedule/<int:id>')
@login_required
def team_schedule(id):
    team = Team.query.get_or_404(id)
    if id == 1:
        team.school = "中国科学技术大学" 
    
    # 获取回放数据
    replay_links = {}
    try:
        if os.path.exists(REPLAY_DATA_FILE):
            with open(REPLAY_DATA_FILE, 'r', encoding='utf-8') as f:
                replay_json = json.load(f)
                
            # 提取回放链接 - 直接使用ID为键
            if 'simple_cms' in replay_json:
                for item in replay_json.get('simple_cms', []):
                    if item.get('is_active', False):
                        content = item.get('content', {})
                        main_remote_url = content.get('main_remote_url', '')
                        # 使用item的id作为键，这个id应与比赛id匹配
                        match_id = str(item.get("content").get("match_id", ""))  # 确保获取到正确的比赛ID
                        if not match_id:
                            continue
                        if match_id and main_remote_url:
                            replay_links[match_id] = main_remote_url
                            # print(f"找到回放链接: ID={match_id}, URL={main_remote_url}")
    except Exception as e:
        print(f"解析回放数据错误: {str(e)}")
    
    # print(f"所有回放链接: {replay_links}")
    
    # 从JSON文件获取赛程数据
    schedule_data = []
    try:
        if os.path.exists(SCHEDULE_DATA_FILE):
            with open(SCHEDULE_DATA_FILE, 'r', encoding='utf-8') as f:
                schedule_json = json.load(f)
                
            # 解析JSON数据，提取所有比赛
            all_matches = []
            
            # 检查必要的字段是否存在
            if ('data' in schedule_json and 
                'event' in schedule_json.get('data', {}) and 
                'zones' in schedule_json.get('data', {}).get('event', {})):
                
                # 修复: 确保zones不是None，且安全地获取nodes
                zones_data = schedule_json['data']['event']['zones']
                title = schedule_json['data']['event'].get('title', '未知赛事')
                
                print(f"正在处理赛事: {title}")
                if zones_data is not None:
                    zones = zones_data.get('nodes', [])
                else:
                    zones = []
                
                for zone in zones:
                    # 获取小组赛 - 确保安全访问
                    group_matches = zone.get('groupMatches', {})
                    if group_matches is not None:
                        all_matches.extend(group_matches.get('nodes', []))
                    
                    # 获取淘汰赛 - 确保安全访问
                    knockout_matches = zone.get('knockoutMatches', {})
                    if knockout_matches is not None:
                        all_matches.extend(knockout_matches.get('nodes', []))
            
            # 找出与当前队伍相关的比赛
            team_matches = []
            
            for match in all_matches:
                # 安全获取嵌套字段
                red_side = {}
                blue_side = {}
                
                if match.get('redSide') and match['redSide'].get('player') and match['redSide']['player'].get('team'):
                    red_side = match['redSide']['player']['team']
                
                if match.get('blueSide') and match['blueSide'].get('player') and match['blueSide']['player'].get('team'):
                    blue_side = match['blueSide']['player']['team']
                
                # 检查队伍名称和学校名称是否匹配
                if (red_side.get('collegeName') == team.school or blue_side.get('collegeName') == team.school):
                    # 基本赛事信息
                    # 解析形如'2025-05-21T06:20:00Z'格式时间
                    time = match.get('planStartedAt', '')
                    if time:
                        from datetime import datetime
                        time = datetime.strptime(time, "%Y-%m-%dT%H:%M:%SZ")
                    division = ''
                    # 如果time的月份在七月之前则在title后面添加一个分区赛
                    if time.month < 7:
                        division = " - 分区赛"
                    else:
                        division += " - 全国总决赛与复活赛"
                    match_info = {
                        'id': match.get('id'),
                        'title': title + division,
                        'match_type': match.get('matchType', 'GROUP'),
                        'status': match.get('status'),
                        'result': match.get('result'),
                        'plan_game_count': match.get('planGameCount', 3),
                        'start_time': match.get('planStartedAt'),
                        'planStartedAt': match.get('planStartedAt'),
                        
                        # 红方信息
                        'red_team': {
                            'name': red_side.get('name', ''),
                            'college': red_side.get('collegeName', ''),
                            'logo': red_side.get('collegeLogo', ''),
                            'rank': match.get('redSide', {}).get('player', {}).get('rank') if match.get('redSide') and match.get('redSide', {}).get('player') else None
                        },
                        'red_score': match.get('redSideScore', 0),
                        'red_win_count': match.get('redSideWinGameCount', 0),
                        
                        # 蓝方信息
                        'blue_team': {
                            'name': blue_side.get('name', ''),
                            'college': blue_side.get('collegeName', ''),
                            'logo': blue_side.get('collegeLogo', ''),
                            'rank': match.get('blueSide', {}).get('player', {}).get('rank') if match.get('blueSide') and match.get('blueSide', {}).get('player') else None
                        },
                        'blue_score': match.get('blueSideScore', 0),
                        'blue_win_count': match.get('blueSideWinGameCount', 0),
                    }
                    
                    # 判断是否是本队伍的比赛
                    if red_side.get('collegeName') == team.school:
                        match_info['is_red'] = True
                        if match.get('result') == 'RED':
                            match_info['is_win'] = True
                        elif match.get('result') == 'BLUE':
                            match_info['is_win'] = False
                    else:
                        match_info['is_red'] = False
                        if match.get('result') == 'BLUE':
                            match_info['is_win'] = True
                        elif match.get('result') == 'RED':
                            match_info['is_win'] = False
                    
                    # 格式化时间 (UTC转本地时间)
                    if match_info['start_time']:
                        try:
                            from datetime import datetime
                            import pytz
                            # 解析UTC时间
                            utc_time = datetime.strptime(match_info['start_time'], "%Y-%m-%dT%H:%M:%SZ")
                            # 添加时区信息
                            utc_time = pytz.utc.localize(utc_time)
                            # 转换为北京时间
                            beijing_tz = pytz.timezone('Asia/Shanghai')
                            beijing_time = utc_time.astimezone(beijing_tz)
                            # 格式化
                            match_info['formatted_time'] = beijing_time.strftime("%Y-%m-%d %H:%M")
                            # 获取比赛的起始日


                        except Exception as e:
                            print(f"时间解析错误: {e}")
                            match_info['formatted_time'] = match_info['start_time']
                            match_info['day_number'] = "?"
                    
                    # 添加回放链接到match_info
                    match_id = str(match.get('id'))
                    match_info['replay_url'] = replay_links.get(match_id, '#')
                    
                    if match_info['replay_url'] != '#':
                        print(f"找到比赛{match_id}的回放: {match_info['replay_url']}")
                    else:
                        print(f"未找到比赛{match_id}的回放")
                    
                    team_matches.append(match_info)
            
            # 按时间排序
            team_matches.sort(key=lambda x: x.get('start_time', ''), reverse=True)
            schedule_data = team_matches
    except Exception as e:
        print(f"解析赛程数据错误: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return render_template('team_schedule.html', team=team, matches=schedule_data)

# 删除队伍
@app.route('/delete_team/<int:id>', methods=['POST'])
@login_required
def delete_team(id):
    team = Team.query.get_or_404(id)
    TacticalData.query.filter_by(team_id=id).delete()  # 先删除关联数据
    db.session.delete(team)
    db.session.commit()
    flash('队伍已删除', 'success')
    return redirect(url_for('index'))

# 战队积分榜页面
@app.route('/team_ranking')
@login_required
def team_ranking():
    try:
        # 如果文件不存在，立即下载
        # if not os.path.exists(GROUP_RANK_FILE):
        #     download_robot_data()
        
        # 读取积分榜数据
        with open(GROUP_RANK_FILE, 'r', encoding='utf-8') as f:
            rank_data = json.load(f)
        
        # 处理和整理数据
        zones_data = []
        
        for zone in rank_data.get('zones', []):
            zone_info = {
                'name': zone.get('zoneName', '未知赛区'),
                'groups': []
            }
            
            for group in zone.get('groups', []):
                group_info = {
                    'name': group.get('groupName', '未知小组'),
                    'teams': []
                }
                # 获取队伍信息
                teams = []
                for player in group.get('groupPlayers', []):
                    # 创建队伍数据结构
                    team = {}
                    # 从项目中提取数据
                    for item in player:
                        item_name = item.get('itemName', '')
                        item_value = item.get('itemValue', '')
                        
                        if item_name == '战队':
                            team['collegeName'] = item_value.get('collegeName', '未知学校')
                            team['teamName'] = item_value.get('teamName', '未知战队')
                            team['collegeLogo'] = item_value.get('collegeLogo', '')
                        elif item_name == '胜/平/负':
                            team['record'] = item_value
                            # 从胜/平/负中提取负场数
                            if isinstance(item_value, str) and '/' in item_value:
                                parts = item_value.split('/')
                                if len(parts) == 3:
                                    try:
                                        team['losses'] = int(parts[2])
                                    except ValueError:
                                        team['losses'] = 0
                                else:
                                    team['losses'] = 0
                            else:
                                team['losses'] = 0
                        elif item_name == '胜场数':
                            team['wins'] = item_value
                        elif item_name == '对手分':
                            team['opponent_score'] = item_value
                        elif item_name == '局均总基地净胜血量':
                            team['base_hp_diff'] = item_value
                        elif item_name == '局均总前哨站净胜血量':
                            team['outpost_hp_diff'] = item_value
                        elif item_name == '局均全队总伤害血量':
                            team['total_damage'] = item_value
                    
                    if team:
                        teams.append(team)
                
                # 按照新优先级排序：胜场数、负场数（越少越靠前）、对手分、局均总基地净胜血量、局均总前哨站净胜血量、局均全队总伤害血量
                teams.sort(key=lambda x: (
                    x.get('wins', 0),  # 胜场数（降序）
                    -x.get('losses', 0),  # 负场数（升序）
                    x.get('opponent_score', 0),  # 对手分（降序）
                    x.get('base_hp_diff', 0),  # 局均总基地净胜血量（降序）
                    x.get('outpost_hp_diff', 0),  # 局均总前哨站净胜血量（降序）
                    x.get('total_damage', 0)  # 局均全队总伤害血量（降序）
                ), reverse=True)
                
                group_info['teams'] = teams
                zone_info['groups'].append(group_info)
            
            zones_data.append(zone_info)
        
        # 获取系统中的所有队伍作为查找字典
        team_dict = {}
        teams = Team.query.all()
        for team in teams:
            team_dict[team.school] = team.id
        
        return render_template('team_ranking.html', zones=zones_data, team_dict=team_dict)
    
    except Exception as e:
        flash(f'加载积分榜数据时出错: {str(e)}', 'error')
        print(f"加载积分榜数据错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return redirect(url_for('index'))

# 添加静态数据路由
@app.route('/robot_data.json')
def serve_robot_data():
    # 如果文件不存在，立即下载一次
    # if not os.path.exists(ROBOT_DATA_FILE):
    #     download_robot_data()
    
    # 从静态文件目录提供文件
    return redirect(url_for('static', filename='data/robot_data.json'))

@app.route('/schedule.json')
def serve_schedule_data():
    # 如果文件不存在，立即下载一次
    # if not os.path.exists(SCHEDULE_DATA_FILE):
    #     download_robot_data()
    
    # 从静态文件目录提供文件
    return redirect(url_for('static', filename='data/schedule.json'))

# 添加路由，获取本地缓存的学校 logo
@app.route('/school_logo/<path:college_name>')
def serve_school_logo(college_name):
    # 创建安全的文件名
    safe_name = ''.join(c if c.isalnum() or c in '_-' else '_' for c in college_name)
    
    # 查找匹配的 logo 文件
    for filename in os.listdir(LOGO_FOLDER):
        name_without_ext = os.path.splitext(filename)[0]
        if name_without_ext == safe_name:
            return redirect(url_for('static', filename=f'logos/{filename}'))
    
    # 如果找不到匹配的 logo，返回默认图片
    return redirect(url_for('static', filename='logos/default.jpg'))

# 同步战术数据分类到数据库
def sync_tactical_categories():
    """
    检查TACTICAL_CATEGORIES是否与数据库匹配，
    若有新增的分类或项目，自动添加到所有队伍的数据中
    若有删除的分类或项目，自动从数据库中删除对应条目
    """
    print("开始同步战术数据分类...")
    
    # 获取所有队伍
    teams = Team.query.all()
    if not teams:
        print("没有找到队伍，跳过同步")
        return
    
    # 创建一个包含所有当前有效分类-项目组合的集合
    valid_items = set()
    for category, items in TACTICAL_CATEGORIES:
        for item in items:
            valid_items.add(f"{category}:{item}")
    
    print(f"当前有效的战术数据条目数量: {len(valid_items)}")
    
    # 跟踪已添加和已删除的条目数量
    total_added = 0
    total_deleted = 0
    
    for team in teams:
        # 获取当前队伍的所有战术数据
        existing_data = TacticalData.query.filter_by(team_id=team.id).all()
        
        # 构建字典以快速查找
        existing_items = {}
        for data in existing_data:
            key = f"{data.category}:{data.item}"
            existing_items[key] = data
        
        # 检查是否需要添加新的战术数据条目
        new_items_added = 0
        
        # 对每个分类和项目检查
        for category, items in TACTICAL_CATEGORIES:
            for item in items:
                key = f"{category}:{item}"
                if key not in existing_items:
                    # 创建新条目
                    new_data = TacticalData(
                        team_id=team.id,
                        category=category,
                        item=item,
                        content=''
                    )
                    db.session.add(new_data)
                    new_items_added += 1
        
        # 检查是否需要删除已不存在的战术数据条目
        items_to_delete = []
        for key, data in existing_items.items():
            if key not in valid_items:
                items_to_delete.append(data)
        
        if items_to_delete:
            for data in items_to_delete:
                db.session.delete(data)
                total_deleted += 1
            print(f"为队伍 {team.school} - {team.team} 删除了 {len(items_to_delete)} 个过期战术数据条目")
        
        if new_items_added > 0:
            print(f"为队伍 {team.school} - {team.team} 添加了 {new_items_added} 个新战术数据条目")
            total_added += new_items_added
    
    if total_added > 0 or total_deleted > 0:
        db.session.commit()
        print(f"战术数据分类同步完成 - 添加了 {total_added} 个条目，删除了 {total_deleted} 个条目")
    else:
        print("战术数据分类已是最新，无需更新")

# 同步队伍小组信息
def sync_team_groups():
    """确保所有队伍都有小组信息，默认为A组"""
    teams = Team.query.filter(Team.group.is_(None)).all()
    if teams:
        for team in teams:
            team.group = 'A'
        db.session.commit()
        print(f"已为{len(teams)}支队伍设置默认小组为A组")

# 数据库迁移函数 - 添加在app.py中适当位置（在数据库模型定义之后）
def migrate_database():
    """检查数据库结构并进行必要的迁移"""
    print("检查数据库结构...")
    
    # 使用原始SQL语句检查team表是否存在group列
    with app.app_context():
        try:
            # 获取team表的结构信息
            result = db.session.execute(db.text("PRAGMA table_info(team)")).fetchall()
            columns = [row[1] for row in result]  # 第二列是列名
            
            # 检查是否存在group列
            if 'group' not in columns:
                print("数据库缺少'group'列，正在添加...")
                # 添加group列，设置默认值为'A'
                db.session.execute(db.text("ALTER TABLE team ADD COLUMN \"group\" VARCHAR(10) DEFAULT 'A'"))
                db.session.commit()
                print("成功添加'group'列")
            else:
                print("数据库结构检查完成，'group'列已存在")
                
        except Exception as e:
            print(f"数据库迁移错误: {str(e)}")
            db.session.rollback()

# 初始化数据库（创建表 + 插入测试数据）
with app.app_context():
    db.create_all()
    
    # 添加数据库迁移步骤
    migrate_database()
    
    if not Team.query.first():
        # 插入预定义队伍
        for team_data in PREDEFINED_TEAMS:
            team = Team(
                school=team_data['school'],
                team=team_data['team'],
                rank=team_data['rank'],
                rank_exam=team_data.get('rank_exam'),
                money=team_data.get('money'),
                comment=team_data.get('comment', ''),
                group='A'  # 默认设置为A组
            )
            db.session.add(team)
            db.session.commit()
            
            # 初始化战术数据
            for category, items in TACTICAL_CATEGORIES:
                for item in items:
                    data = TacticalData(
                        team_id=team.id,
                        category=category,
                        item=item,
                        content=''
                    )
                    db.session.add(data)
        db.session.commit()
    else:
        # 如果已有队伍，检查并同步战术数据分类
        sync_tactical_categories()
        # 同步队伍小组信息
        sync_team_groups()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6060, debug=False)