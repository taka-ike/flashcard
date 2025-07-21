from flask import Flask, render_template, request, redirect, url_for, flash, session
import csv
import random
import re
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # flashメッセージのために必要

# --- 定数 ---
WORDS_CSV_FILE = 'data/words.csv'
PROGRESS_CSV_FILE = 'data/user_progress.csv'
SPACED_REPETITION_INTERVALS = [1, 2, 4, 8, 16, 32, 64] # 日

# AIによる選択肢生成を有効にするか
USE_AI_FOR_CHOICES = True # True にするとAI生成を試みますが、現状はダミー関数です

# --- データ処理 ---

def generate_ai_choices(correct_answer, all_possible_answers, num_choices=4):
    """AIが生成したかのような不正解の選択肢をシミュレートするダミー関数"""
    incorrect_choices = []
    # 正解以外の選択肢をフィルタリング
    other_answers = [ans for ans in all_possible_answers if ans != correct_answer and ans is not None]

    # ここにAIによる選択肢生成ロジックをシミュレートするコードを追加
    # 例: 似たような単語、同じ品詞の単語、ランダムな単語など
    # 今回はシンプルに、ランダムに選択肢を選びます

    if len(other_answers) > 0:
        # 可能な限り、他の正解以外の選択肢から選ぶ
        incorrect_choices = random.sample(other_answers, min(num_choices, len(other_answers)))
    
    # 選択肢が足りない場合はNoneで埋めるか、空のままにする
    while len(incorrect_choices) < num_choices:
        incorrect_choices.append(None) # または適切なダミー値

    return [choice for choice in incorrect_choices if choice is not None]


def parse_sentence(sentence):
    match = re.search(r'__(.*?)__', sentence)
    if match:
        word = match.group(1)
        underlined_sentence = sentence.replace(f'__{word}__', f'<u>{word}</u>')
        blank_sentence = sentence.replace(f'__{word}__', '＿＿＿＿')
        return underlined_sentence, blank_sentence, word
    return sentence, sentence, None

def get_all_data():
    words = {}
    try:
        with open(WORDS_CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader) # header
            for row in reader:
                if len(row) < 2: continue
                eng_full = row[0]
                jap_full = row[1]
                eng_underlined, eng_blank, eng_word = parse_sentence(eng_full)
                jap_underlined, jap_blank, jap_word = parse_sentence(jap_full)
                words[row[0]] = {
                    'english_full': eng_full,
                    'japanese_full': jap_full,
                    'english_underlined': eng_underlined,
                    'japanese_underlined': jap_underlined,
                    'english_blank': eng_blank,
                    'japanese_blank': jap_blank,
                    'english_word': eng_word,
                    'japanese_word': jap_word,
                }
    except FileNotFoundError:
        return {}

    progress = {}
    try:
        with open(PROGRESS_CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                progress[row['english_full']] = row
    except FileNotFoundError:
        pass

    # 単語データと進捗データをマージ
    for eng_full, word_data in words.items():
        if eng_full not in progress:
            progress[eng_full] = {
                'english_full': eng_full,
                'last_reviewed': 'N/A',
                'next_review_date': datetime.now().strftime('%Y-%m-%d'),
                'correct_streak': 0,
                'total_correct': 0,
                'total_incorrect': 0
            }
        words[eng_full].update(progress[eng_full])
    
    # 数値データを正しい型に変換
    for word in words.values():
        word['correct_streak'] = int(word.get('correct_streak', 0))
        word['total_correct'] = int(word.get('total_correct', 0))
        word['total_incorrect'] = int(word.get('total_incorrect', 0))
        word['accuracy'] = (word['total_correct'] / (word['total_correct'] + word['total_incorrect'])) if (word['total_correct'] + word['total_incorrect']) > 0 else 0

    return list(words.values())

def write_progress_data(all_data):
    with open(PROGRESS_CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['english_full', 'last_reviewed', 'next_review_date', 'correct_streak', 'total_correct', 'total_incorrect']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for word in all_data:
            progress_data = {key: word.get(key) for key in fieldnames}
            writer.writerow(progress_data)

MEANINGS_CSV_FILE = 'data/meanings.csv'

def get_meanings():
    meanings = []
    try:
        with open(MEANINGS_CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                meanings.append(row)
    except FileNotFoundError:
        pass
    return meanings

def write_meanings(meanings):
    with open(MEANINGS_CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['word', 'meaning']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(meanings)

# --- クイズロジック ---



# --- Flaskルート ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/quiz')
def quiz():
    mode = request.args.get('mode', 'random')
    quiz_type = request.args.get('quiz_type', 'en_to_jp')

    if 'quiz_questions' not in session or not session['quiz_questions']:
        all_data = get_all_data()
        if not all_data:
            flash('単語が登録されていません。データベースを編集してください。')
            return redirect(url_for('edit_db'))

        # フィルタリングロジックはそのまま
        if mode == 'review':
            today = datetime.now().date()
            filtered_data = [w for w in all_data if datetime.strptime(w['next_review_date'], '%Y-%m-%d').date() <= today]
        elif mode == 'difficult':
            filtered_data = [w for w in all_data if w['accuracy'] < 0.5 or w['total_incorrect'] >= 5]
        else: # random
            filtered_data = all_data

        if not filtered_data:
            flash(f'{mode.capitalize()}モードで出題できる問題がありません。')
            return redirect(url_for('index'))

        session['quiz_questions'] = random.sample(filtered_data, len(filtered_data)) # シャッフルしてセッションに保存
        session['current_question_index'] = 0
        session['total_questions'] = len(session['quiz_questions'])
        session['quiz_mode'] = mode # セッションにモードを保存
        session['quiz_type'] = quiz_type # セッションにクイズタイプを保存
        session['session_results'] = [] # 今のセッションでの結果を保存

    if session['current_question_index'] >= session['total_questions']:
        # すべての問題が終了したらサマリーページへリダイレクト
        total_answered = len(session['session_results'])
        correct_count = sum(1 for _, is_correct in session['session_results'] if is_correct)
        accuracy = (correct_count / total_answered * 100) if total_answered > 0 else 0

        incorrect_questions_data = [q_data for q_data, is_correct in session['session_results'] if not is_correct]
        session['last_incorrect_questions'] = incorrect_questions_data # セッションに保存

        # セッションをクリア
        session.pop('quiz_questions', None)
        session.pop('current_question_index', None)
        session.pop('total_questions', None)
        session.pop('quiz_mode', None)
        session.pop('quiz_type', None)
        session.pop('incorrect_questions', None) # 以前の不正解リストもクリア
        session.pop('session_results', None)

        return redirect(url_for('quiz_summary', accuracy=f'{accuracy:.2f}', incorrect_count=len(incorrect_questions_data)))

    word_data = session['quiz_questions'][session['current_question_index']]

    # --- 問題と選択肢の準備 ---
    question = ""
    correct_answer = ""
    all_answers = []

    eng_full = word_data['english_full']
    jap_full = word_data['japanese_full']
    eng_underlined = word_data['english_underlined']
    jap_underlined = word_data['japanese_underlined']
    eng_blank = word_data['english_blank']
    jap_blank = word_data['japanese_blank']
    eng_word = word_data['english_word']
    jap_word = word_data['japanese_word']

    # all_dataを再度取得して、選択肢生成に使う
    all_data_for_choices = get_all_data()

    if quiz_type == 'en_to_jp':
        question = eng_underlined
        correct_answer = jap_word
        all_answers = [w['japanese_word'] for w in all_data_for_choices if w['japanese_word'] is not None]
    elif quiz_type == 'jp_to_en':
        question = jap_underlined
        correct_answer = eng_word
        all_answers = [w['english_word'] for w in all_data_for_choices if w['english_word'] is not None]
    elif quiz_type == 'fill_en':
        question = eng_blank
        correct_answer = eng_word
        all_answers = [w['english_word'] for w in all_data_for_choices if w['english_word'] is not None]
    elif quiz_type == 'fill_jp':
        question = jap_blank
        correct_answer = jap_word
        all_answers = [w['japanese_word'] for w in all_data_for_choices if w['japanese_word'] is not None]

    choices = generate_choices(all_answers, correct_answer)

    return render_template('quiz.html',
                           question=question,
                           choices=choices,
                           mode=session['quiz_mode'],
                           quiz_type=session['quiz_type'],
                           word=word_data,
                           correct_answer=correct_answer,
                           current_question_index=session['current_question_index'] + 1, # 1から始まるように
                           total_questions=session['total_questions'])

def generate_choices(all_answers, correct_answer):
    """正解１つ、不正解４つの選択肢を生成する"""
    other_answers = list(set([ans for ans in all_answers if ans != correct_answer and ans is not None]))
    num_choices = min(4, len(other_answers))
    
    choices = random.sample(other_answers, num_choices)
    choices.append(correct_answer)
    random.shuffle(choices)
    return choices

@app.route('/answer', methods=['POST'])
def answer():
    user_choice = request.form['choice']
    correct_answer = request.form['correct_answer']
    eng_full = request.form['english_full']
    mode = request.form['mode']
    quiz_type = request.form['quiz_type'] # quiz_type を取得
    is_correct = (user_choice == correct_answer)

    all_data = get_all_data()
    target_word = next((w for w in all_data if w['english_full'] == eng_full), None)

    if target_word:
        target_word['last_reviewed'] = datetime.now().strftime('%Y-%m-%d')
        if is_correct:
            target_word['total_correct'] += 1
            target_word['correct_streak'] += 1
            interval_days = SPACED_REPETITION_INTERVALS[min(target_word['correct_streak'], len(SPACED_REPETITION_INTERVALS) - 1)]
            target_word['next_review_date'] = (datetime.now() + timedelta(days=interval_days)).strftime('%Y-%m-%d')
            flash('正解！', 'success')
        else:
            target_word['total_incorrect'] += 1
            target_word['correct_streak'] = 0
            target_word['next_review_date'] = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
            flash(f'不正解... 正解は {correct_answer} でした。', 'error')
            if 'incorrect_questions' not in session:
                session['incorrect_questions'] = []
            session['incorrect_questions'].append(target_word) # 不正解だった問題をセッションに保存

        write_progress_data(all_data)

    # セッション結果を記録
    if 'session_results' not in session:
        session['session_results'] = []
    session['session_results'].append((target_word, is_correct))
    
    session['current_question_index'] += 1
    return redirect(url_for('quiz', mode=mode, quiz_type=quiz_type))

@app.route('/meaning_quiz')
def meaning_quiz():
    mode = request.args.get('mode', 'word_to_meaning')

    if 'meaning_quiz_questions' not in session or not session['meaning_quiz_questions']:
        meanings = get_meanings()
        if not meanings:
            flash('言葉の意味が登録されていません。データベースを編集してください。')
            return redirect(url_for('edit_meanings'))

        session['meaning_quiz_questions'] = random.sample(meanings, len(meanings)) # シャッフルしてセッションに保存
        session['current_meaning_question_index'] = 0
        session['total_meaning_questions'] = len(session['meaning_quiz_questions'])
        session['meaning_quiz_mode'] = mode # セッションにモードを保存

    if session['current_meaning_question_index'] >= session['total_meaning_questions']:
        if 'incorrect_meaning_questions' in session and session['incorrect_meaning_questions']:
            # 不正解だった問題を再度出題リストに追加し、シャッフル
            session['meaning_quiz_questions'].extend(session['incorrect_meaning_questions'])
            random.shuffle(session['meaning_quiz_questions'])
            session['current_meaning_question_index'] = 0
            session['total_meaning_questions'] = len(session['meaning_quiz_questions'])
            session['incorrect_meaning_questions'] = [] # リセット
            flash('不正解だった言葉の意味問題を再度出題します。', 'info')
        else:
            flash('すべての言葉の意味問題が終了しました！', 'success')
            session.pop('meaning_quiz_questions', None)
            session.pop('current_meaning_question_index', None)
            session.pop('total_meaning_questions', None)
            session.pop('meaning_quiz_mode', None)
            session.pop('incorrect_meaning_questions', None)
            return redirect(url_for('index'))

    meaning_data = session['meaning_quiz_questions'][session['current_meaning_question_index']]

    question = ""
    correct_answer = ""
    all_answers = []

    # all_dataを再度取得して、選択肢生成に使う
    all_meanings_for_choices = get_meanings()

    if mode == 'word_to_meaning':
        question = meaning_data['word']
        correct_answer = meaning_data['meaning']
        all_answers = [m['meaning'] for m in all_meanings_for_choices]
    elif mode == 'meaning_to_word':
        question = meaning_data['meaning']
        correct_answer = meaning_data['word']
        all_answers = [m['word'] for m in all_meanings_for_choices]

    choices = generate_choices(all_answers, correct_answer)

    return render_template('meaning_quiz.html',
                           question=question,
                           choices=choices,
                           mode=session['meaning_quiz_mode'],
                           correct_answer=correct_answer,
                           current_question_index=session['current_meaning_question_index'] + 1, # 1から始まるように
                           total_questions=session['total_meaning_questions'])

@app.route('/meaning_answer', methods=['POST'])
def meaning_answer():
    user_choice = request.form['choice']
    correct_answer = request.form['correct_answer']
    question = request.form['question']
    mode = request.form['mode']

    is_correct = (user_choice == correct_answer)

    if is_correct:
        flash('正解！', 'success')
    else:
        flash(f'不正解... 正解は {correct_answer} でした。', 'error')
        # 不正解だった問題をセッションに保存
        if 'incorrect_meaning_questions' not in session:
            session['incorrect_meaning_questions'] = []
        # 現在の問題データを取得して保存
        current_meaning_question = session['meaning_quiz_questions'][session['current_meaning_question_index']]
        session['incorrect_meaning_questions'].append(current_meaning_question)

    session['current_meaning_question_index'] += 1
    return redirect(url_for('meaning_quiz', mode=mode))

@app.route('/quiz_summary')
def quiz_summary():
    accuracy = request.args.get('accuracy', '0.00')
    incorrect_count = request.args.get('incorrect_count', 0)
    
    # 不正解だった問題のデータをセッションから取得
    incorrect_questions_data = session.get('last_incorrect_questions', [])
    
    return render_template('quiz_summary.html', accuracy=accuracy, incorrect_count=incorrect_count, incorrect_questions=incorrect_questions_data)

@app.route('/start_incorrect_quiz')
def start_incorrect_quiz():
    # 不正解だった問題のみでクイズを再開
    incorrect_questions = session.get('last_incorrect_questions', [])
    if not incorrect_questions:
        flash('不正解だった問題がありません。', 'info')
        return redirect(url_for('index'))

    session['quiz_questions'] = random.sample(incorrect_questions, len(incorrect_questions))
    session['current_question_index'] = 0
    session['total_questions'] = len(session['quiz_questions'])
    session['quiz_mode'] = 'incorrect_review' # 新しいモード
    session['quiz_type'] = 'en_to_jp' # または前回のクイズタイプを保持
    session['session_results'] = []
    session.pop('last_incorrect_questions', None) # 使用したのでクリア

    return redirect(url_for('quiz'))

@app.route('/start_all_quiz')
def start_all_quiz():
    # 全問題でクイズを再開
    session.pop('quiz_questions', None)
    session.pop('current_question_index', None)
    session.pop('total_questions', None)
    session.pop('quiz_mode', None)
    session.pop('quiz_type', None)
    session.pop('session_results', None)
    session.pop('last_incorrect_questions', None)

    return redirect(url_for('quiz', mode='random')) # デフォルトのランダムモードで開始

@app.route('/edit')
def edit_db():
    words = get_all_data()
    return render_template('edit.html', words=words)

@app.route('/update', methods=['POST'])
def update_db():
    english_words = request.form.getlist('english_full')
    japanese_words = request.form.getlist('japanese_full')
    
    # 単語データの更新
    new_words_data = []
    for eng, jap in zip(english_words, japanese_words):
        if eng and jap:
            new_words_data.append({'english': eng, 'japanese': jap})
    with open(WORDS_CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['english', 'japanese'])
        for word in new_words_data:
            writer.writerow([word['english'], word['japanese']])

    # 進捗データも同期
    all_data = get_all_data()
    write_progress_data(all_data)

    # クイズセッションをリセット
    session.pop('quiz_questions', None)
    session.pop('current_question_index', None)
    session.pop('total_questions', None)
    session.pop('quiz_mode', None)
    session.pop('quiz_type', None)
    session.pop('session_results', None)
    session.pop('incorrect_questions', None)
    session.pop('last_incorrect_questions', None)
    session.pop('meaning_quiz_questions', None)
    session.pop('current_meaning_question_index', None)
    session.pop('total_meaning_questions', None)
    session.pop('meaning_quiz_mode', None)
    session.pop('incorrect_meaning_questions', None)

    flash('データベースが更新されました。')
    words = get_all_data()
    return render_template('edit.html', words=words)

@app.route('/edit_meanings')
def edit_meanings():
    meanings = get_meanings()
    return render_template('edit_meanings.html', meanings=meanings)

@app.route('/update_meanings', methods=['POST'])
def update_meanings():
    words = request.form.getlist('word')
    meanings = request.form.getlist('meaning')
    
    new_meanings_data = []
    for w, m in zip(words, meanings):
        if w and m:
            new_meanings_data.append({'word': w, 'meaning': m})
            
    write_meanings(new_meanings_data)
    flash('言葉の意味データベースが更新されました。')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
