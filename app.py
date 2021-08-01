from flask import Flask, render_template, request, redirect, url_for, flash, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
import datetime
import numpy as np
from io import StringIO
import subprocess
from pathlib import Path

app = Flask(__name__)
app.config['SECRET_KEY'] = 'zfb33782323cc152019b747a051f73c6'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

ITEMS = np.loadtxt(
    'items.csv',
    delimiter=',',
    skiprows=1,
    dtype=[
        ('product_id', 'str'),
        ('price', 'int'),
        ('cost', 'int'),
        ('review_score', 'float'),
        ('product_name_length', 'int'),
        ('product_description_length', 'int'),
        ('product_photos_qty', 'int'),
        ('product_weight_g', 'int'),
        ('product_length_cm', 'int'),
        ('product_height_cm', 'int'),
        ('product_width_cm', 'int')
    ]
)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)


class User(db.Model, UserMixin):
    username = db.Column(db.Text, nullable=False, primary_key=True)
    password = db.Column(db.Text, nullable=False)

    def get_id(self):
        return self.username


class Submission(db.Model):
    id = db.Column(db.Integer, nullable=False, primary_key=True, autoincrement=True)
    username = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    submission = db.Column(db.Text, nullable=False)
    demands = db.Column(db.Text, nullable=False)
    score = db.Column(db.Float, nullable=False)


db.create_all()


@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.get(request.form['username'])
        if user and user.password == request.form['password']:
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('my_page'))
        else:
            flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        new_user = User()
        new_user.username = request.form['username']
        new_user.password = request.form['password']
        try:
            db.session.add(new_user)
            db.session.commit()
            return '''
            <p>ユーザー登録に成功しました</p>
            <a href="/">ログイン画面</a>
            '''
        except Exception as e:
            return f'''
            <p>ユーザー登録に失敗しました</p>
            <p>{e}</p>
            <a href="/signup">戻る</a>
            '''
    return render_template('signup.html')


@app.route('/mypage')
@login_required
def my_page():
    submissions = Submission.query \
        .filter_by(username=current_user.username) \
        .order_by(Submission.date.desc()) \
        .all()
    sub_all = Submission.query.order_by(Submission.id).all()
    leaderboard = {}
    for sub in sub_all:
        leaderboard[sub.username] = sub.score
    print(leaderboard)
    return render_template('mypage.html',
                           submissions=submissions,
                           leaderboard=leaderboard
                           )


@app.route('/submission', methods=['POST'])
@login_required
def submission():
    # 投稿されたファイルをCSVファイルとして一時保存
    try:
        fs = request.files['file']
        fs.save('./submission_tmp.csv')
    except Exception as e:
        flash(f'ファイル読み込みに失敗しました\n${e}', 'error')
        return redirect(url_for('my_page'))

    # 投稿されたデータのCSVを引数にして販売数を返す
    subprocess.Popen('"./venv/Scripts/activate.bat" && python "./out_demand/demand.py" '
                     '--file-path submission_tmp.csv --options-path out_demand/data/opt.json'
                     ' --out-path demand_tmp.csv').wait()

    # 予測csv, 販売数csvからnumpy行列を抽出
    submission_array = np.loadtxt('submission_tmp.csv', delimiter=',', usecols=1)
    demand_array = np.loadtxt('demand_tmp.csv', delimiter=',', usecols=1)

    # 売上個数のnumpy行列をスコア（利益）算出関数に渡す
    profit = calculate_profit(submission_array, demand_array)

    # 結果をDBに格納
    try:
        submission_entity = Submission()
        submission_entity.username = current_user.username
        submission_entity.submission = Path('submission_tmp.csv').read_text()
        submission_entity.demands = Path('demand_tmp.csv').read_text()
        submission_entity.score = profit
        submission_entity.date = datetime.datetime.now()

        db.session.add(submission_entity)
        db.session.commit()
        flash('提出された価格から売上個数を計算しました', 'info')
    except Exception as e:
        flash(f'売上個数の登録に失敗しました\n{e}', 'danger')

    # 一時ファイル削除

    return redirect(url_for('my_page'))


@app.route('/submissions/<string:index>')
@login_required
def download_submission(index):
    index = int(index)
    submission_data = Submission.query \
        .filter_by(username=current_user.username) \
        .order_by(Submission.date.desc()) \
        .all()[index - 1].submission

    response = make_response()
    response.data = submission_data
    filename = f'{current_user.username}_submit_{"{:02d}".format(index)}.csv'
    response.headers['Content-Disposition'] = 'attachment; filename=' + filename
    response.mimetype = 'text/csv'
    return response


@app.route('/demands/<string:index>')
@login_required
def download_demand(index):
    demand_data = Submission.query \
        .filter_by(username=current_user.username) \
        .order_by(Submission.date.desc()) \
        .all()[int(index) - 1].demands

    response = make_response()
    response.data = demand_data
    filename = f'{current_user.username}_demand_{index}.csv'
    response.headers['Content-Disposition'] = 'attachment; filename=' + filename
    response.mimetype = 'text/csv'
    return response


def submission_to_np(submission_txt: str):
    try:
        c = StringIO(submission_txt)
        array = np.loadtxt(
            c,
            delimiter=',',
            dtype=[('product_id', '<U11'), ('price', 'int')]
        )

    except Exception as e:
        raise Exception(f'提出ファイルをnumpy配列に変換できませんでした: {e}')
    if array.shape == (783,):
        return array
    else:
        raise Exception(f'提出ファイルのshapeが正しくありません: {array.shape}')


def calculate_demands(submission_array: np.ndarray) -> np.ndarray:
    blackboxes = BlackBoxFunc.query.all()
    demands_all = list()
    for blackbox in blackboxes:
        exec(blackbox.func, globals())
        exec('explain_funcs = [func(*x) for x in ITEMS]')
        exec('demands = [f(*x) for f,x in zip(explain_funcs, submission_array)]')
        exec('demands_all.append(demands)')
    demands_all_array = np.array(demands_all)
    demands_all_array = demands_all_array.reshape(783, -1)
    demands_ave = np.average(demands_all_array, axis=1).astype('int')
    return demands_ave


def to_csv_string(array: np.ndarray):
    string_1d = [','.join([str(y) for y in x]) for x in array]
    string_2d = '\n'.join(string_1d)
    return string_2d


def calculate_profit(prices, demands):
    return sum([(price - cost) * demands for price, demands, cost in
                zip(prices, demands, ITEMS['cost'])])
