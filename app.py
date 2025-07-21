from flask import Flask, render_template, request, redirect, url_for, flash
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

# --- データ処理 ---

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

def get_quiz_word(all_data, mode):
    today = datetime.now().date()
    if mode == 'review':
        review_words = [w for w in all_data if datetime.strptime(w['next_review_date'], '%Y-%m-%d').date() <= today]
        return random.choice(review_words) if review_words else None
    elif mode == 'difficult':
        # 正解率が50%未満、または5回以上間違えている単語を抽出
        difficult_words = [w for w in all_data if w['accuracy'] < 0.5 or w['total_incorrect'] >= 5]
        return random.choice(difficult_words) if difficult_words else None
    else:
        return random.choice(all_data) if all_data else None

# --- Flaskルート ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/quiz')
def quiz():
    mode = request.args.get('mode', 'random')
    all_data = get_all_data()
    if not all_data:
        flash('単語が登録されていません。データベースを編集してください。')
        return redirect(url_for('edit_db'))

    word_data = get_quiz_word(all_data, mode)
    if not word_data:
        flash(f'{mode.capitalize()}モードで出題できる問題がありません。')
        return redirect(url_for('index'))

    quiz_type = request.args.get('quiz_type', 'en_to_jp') # 新しいパラメータ

    # --- 問題と選択肢の準備 ---
    question = ""
    correct_answer = ""
    choices = []
    all_answers = []

    # word_dataから必要な情報を抽出
    # parse_sentenceはget_all_dataで既に実行済みなので、word_dataから直接取得
    eng_full = word_data['english_full']
    jap_full = word_data['japanese_full']
    eng_underlined = word_data['english_underlined']
    jap_underlined = word_data['japanese_underlined']
    eng_blank = word_data['english_blank']
    jap_blank = word_data['japanese_blank']
    eng_word = word_data['english_word']
    jap_word = word_data['japanese_word']

    if quiz_type == 'en_to_jp':
        question = eng_underlined
        correct_answer = jap_word
        all_answers = [w['japanese_word'] for w in all_data if w['japanese_word'] is not None]
    elif quiz_type == 'jp_to_en':
        question = jap_underlined
        correct_answer = eng_word
        all_answers = [w['english_word'] for w in all_data if w['english_word'] is not None]
    elif quiz_type == 'fill_en':
        question = eng_blank
        correct_answer = eng_word
        all_answers = [w['english_word'] for w in all_data if w['english_word'] is not None]
    elif quiz_type == 'fill_jp':
        question = jap_blank
        correct_answer = jap_word
        all_answers = [w['japanese_word'] for w in all_data if w['japanese_word'] is not None]

    # 選択肢を生成
    choices = generate_choices(all_answers, correct_answer)

    return render_template('quiz.html', question=question, choices=choices, mode=mode, quiz_type=quiz_type, word=word_data, correct_answer=correct_answer)

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
        else:
            target_word['total_incorrect'] += 1
            target_word['correct_streak'] = 0
            target_word['next_review_date'] = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        write_progress_data(all_data)

    return render_template('answer.html', is_correct=is_correct, question=request.form['question'], correct_answer=correct_answer, mode=mode, quiz_type=quiz_type)

@app.route('/meaning_quiz')
def meaning_quiz():
    mode = request.args.get('mode', 'word_to_meaning')
    meanings = get_meanings()
    if not meanings:
        flash('言葉の意味が登録されていません。データベースを編集してください。')
        return redirect(url_for('edit_meanings'))

    meaning_data = random.choice(meanings)
    question = ""
    correct_answer = ""
    choices = []
    all_answers = []

    if mode == 'word_to_meaning':
        question = meaning_data['word']
        correct_answer = meaning_data['meaning']
        all_answers = [m['meaning'] for m in meanings]
    elif mode == 'meaning_to_word':
        question = meaning_data['meaning']
        correct_answer = meaning_data['word']
        all_answers = [m['word'] for m in meanings]

    choices = generate_choices(all_answers, correct_answer)

    return render_template('meaning_quiz.html', question=question, choices=choices, mode=mode, correct_answer=correct_answer)

@app.route('/meaning_answer', methods=['POST'])
def meaning_answer():
    user_choice = request.form['choice']
    correct_answer = request.form['correct_answer']
    question = request.form['question']
    mode = request.form['mode']

    is_correct = (user_choice == correct_answer)

    return render_template('meaning_answer.html', is_correct=is_correct, question=question, correct_answer=correct_answer, mode=mode)

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

    flash('データベースが更新されました。')
    return redirect(url_for('index'))

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
