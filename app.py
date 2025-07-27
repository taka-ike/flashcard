from flask import Flask, render_template, request, redirect, url_for, flash, session
import csv
import random
import re
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# --- 定数 ---
WORDS_CSV_FILE = 'data/words.csv'
PROGRESS_CSV_FILE = 'data/user_progress.csv'
MEANINGS_CSV_FILE = 'data/meanings.csv'
SPACED_REPETITION_INTERVALS = [1, 2, 4, 8, 16, 32, 64]

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
            next(reader)
            for row in reader:
                if len(row) < 2: continue
                eng_full, jap_full = row[0], row[1]
                eng_underlined, eng_blank, eng_word = parse_sentence(eng_full)
                jap_underlined, jap_blank, jap_word = parse_sentence(jap_full)
                words[eng_full] = {
                    'english_full': eng_full, 'japanese_full': jap_full,
                    'english_underlined': eng_underlined, 'japanese_underlined': jap_underlined,
                    'english_blank': eng_blank, 'japanese_blank': jap_blank,
                    'english_word': eng_word, 'japanese_word': jap_word,
                }
    except FileNotFoundError:
        return []

    progress = {}
    try:
        with open(PROGRESS_CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                progress[row['english_full']] = row
    except FileNotFoundError:
        pass

    for eng_full, word_data in words.items():
        if eng_full not in progress:
            progress[eng_full] = {
                'english_full': eng_full, 'last_reviewed': 'N/A',
                'next_review_date': datetime.now().strftime('%Y-%m-%d'),
                'correct_streak': 0, 'total_correct': 0, 'total_incorrect': 0
            }
        words[eng_full].update(progress[eng_full])

    for word in words.values():
        word['correct_streak'] = int(word.get('correct_streak', 0))
        word['total_correct'] = int(word.get('total_correct', 0))
        word['total_incorrect'] = int(word.get('total_incorrect', 0))
        total = word['total_correct'] + word['total_incorrect']
        word['accuracy'] = (word['total_correct'] / total) if total > 0 else 0

    return list(words.values())

def write_progress_data(all_data):
    with open(PROGRESS_CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['english_full', 'last_reviewed', 'next_review_date', 'correct_streak', 'total_correct', 'total_incorrect']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for word in all_data:
            writer.writerow({key: word.get(key) for key in fieldnames})

def get_meanings():
    try:
        with open(MEANINGS_CSV_FILE, 'r', encoding='utf-8') as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []

def write_meanings(meanings):
    with open(MEANINGS_CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['word', 'meaning']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(meanings)

def generate_choices(all_answers, correct_answer):
    other_answers = list(set(ans for ans in all_answers if ans != correct_answer and ans is not None))
    num_choices = min(4, len(other_answers))
    choices = random.sample(other_answers, num_choices)
    choices.append(correct_answer)
    random.shuffle(choices)
    return choices

def get_shuffled_data(data, seed):
    r = random.Random(seed)
    r.shuffle(data)
    return data

# --- クイズロジック ---

def get_quiz_questions(mode):
    all_data = get_all_data()
    if mode == 'review':
        today = datetime.now().date()
        return [w for w in all_data if datetime.strptime(w['next_review_date'], '%Y-%m-%d').date() <= today]
    elif mode == 'difficult':
        return [w for w in all_data if w['accuracy'] < 0.5 or w['total_incorrect'] >= 5]
    elif mode == 'incorrect_review':
        incorrect_ids = session.get('incorrect_ids_for_review', [])
        if not incorrect_ids:
            return [] # 空のリストを返す
        return [q for q in all_data if q['english_full'] in incorrect_ids]
    else: # random
        return all_data

# --- Flaskルート ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/quiz')
def quiz():
    # --- クイズのセットアップ ---
    # 新しいクイズを開始する場合
    if request.args.get('mode'):
        # 必要なセッション情報のみを保持し、他をクリア
        last_incorrect = session.get('last_incorrect_questions', [])
        keys_to_keep = {'last_incorrect_questions': last_incorrect}
        session.clear()
        session.update(keys_to_keep)

        current_mode = request.args.get('mode')
        session['quiz_mode'] = current_mode
        session['quiz_type'] = request.args.get('quiz_type', 'en_to_jp')
        session['quiz_seed'] = random.randint(0, 10000)
        session['current_question_index'] = 0
        session['correct_count'] = 0
        session['incorrect_ids'] = []

        if current_mode == 'incorrect_review':
            last_incorrect_questions = session.get('last_incorrect_questions', [])
            if not last_incorrect_questions:
                flash('再挑戦する問題が見つかりませんでした。', 'error')
                return render_template('quiz_start_error.html', message='再挑戦する問題が見つかりませんでした。')
            
            # incorrect_reviewモード専用のIDリストをセッションに保存
            session['incorrect_ids_for_review'] = [q['english_full'] for q in last_incorrect_questions]
            # last_incorrect_questionsは不要になったので削除
            session.pop('last_incorrect_questions', None)

    if 'quiz_seed' not in session:
        flash('クイズセッションが開始されていません。', 'error')
        return redirect(url_for('index'))

    # --- 問題リストの再構築 ---
    mode = session.get('quiz_mode', 'random')
    questions = get_quiz_questions(mode)
    
    if not questions:
        message = f'{mode.capitalize()}モードで出題できる問題がありません。'
        session.clear()
        return render_template('quiz_start_error.html', message=message)

    questions = get_shuffled_data(questions, session['quiz_seed'])

    # --- 問題表示ロジック ---
    current_index = session.get('current_question_index', 0)
    if current_index >= len(questions):
        correct_count = session.get('correct_count', 0)
        total_answered = len(questions)
        accuracy = (correct_count / total_answered * 100) if total_answered > 0 else 0
        incorrect_ids = session.get('incorrect_ids', [])
        
        all_data = get_all_data()
        incorrect_questions = [q for q in all_data if q['english_full'] in incorrect_ids]
        session['last_incorrect_questions'] = incorrect_questions
        
        # クイズのメインセッション情報のみクリア
        keys_to_pop = ['quiz_mode', 'quiz_type', 'quiz_seed', 'current_question_index', 'correct_count', 'incorrect_ids']
        for key in keys_to_pop:
            session.pop(key, None)

        return redirect(url_for('quiz_summary', accuracy=f'{accuracy:.2f}', incorrect_count=len(incorrect_questions)))

    word_data = questions[current_index]
    quiz_type = session.get('quiz_type', 'en_to_jp')
    
    all_data_for_choices = get_all_data()
    if quiz_type == 'en_to_jp':
        question, correct_answer = word_data['english_underlined'], word_data['japanese_word']
        all_answers = [w['japanese_word'] for w in all_data_for_choices if w.get('japanese_word')]
    elif quiz_type == 'jp_to_en':
        question, correct_answer = word_data['japanese_underlined'], word_data['english_word']
        all_answers = [w['english_word'] for w in all_data_for_choices if w.get('english_word')]
    else:
        question, correct_answer = word_data['english_blank'], word_data['english_word']
        all_answers = [w['english_word'] for w in all_data_for_choices if w.get('english_word')]

    choices = generate_choices(all_answers, correct_answer)

    return render_template('quiz.html', question=question, choices=choices,
                           mode=mode, quiz_type=quiz_type,
                           word=word_data, correct_answer=correct_answer,
                           current_question_index=current_index + 1,
                           total_questions=len(questions), action_url='answer')

@app.route('/answer', methods=['POST'])
def answer():
    if 'quiz_seed' not in session:
        flash('セッションが切れました。もう一度お試しください。', 'error')
        return redirect(url_for('index'))

    user_choice = request.form['choice']
    correct_answer = request.form['correct_answer']
    eng_full = request.form['english_full']
    is_correct = (user_choice == correct_answer)

    if is_correct:
        session['correct_count'] += 1
        flash('正解！', 'success')
    else:
        session.setdefault('incorrect_ids', []).append(eng_full)
        flash(f'不正解... 正解は {correct_answer} でした。', 'error')

    all_data = get_all_data()
    target_word = next((w for w in all_data if w['english_full'] == eng_full), None)
    if target_word:
        target_word['last_reviewed'] = datetime.now().strftime('%Y-%m-%d')
        if is_correct:
            target_word['total_correct'] += 1
            target_word['correct_streak'] += 1
            interval = SPACED_REPETITION_INTERVALS[min(target_word['correct_streak'], len(SPACED_REPETITION_INTERVALS) - 1)]
            target_word['next_review_date'] = (datetime.now() + timedelta(days=interval)).strftime('%Y-%m-%d')
        else:
            target_word['total_incorrect'] += 1
            target_word['correct_streak'] = 0
            target_word['next_review_date'] = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        write_progress_data(all_data)

    session['current_question_index'] += 1
    return redirect(url_for('quiz'))

# --- 意味クイズ（同様のロジック） ---
@app.route('/meaning_quiz')
def meaning_quiz():
    if request.args.get('mode'):
        session.clear()
        session['meaning_quiz_mode'] = request.args.get('mode')
        session['meaning_quiz_seed'] = random.randint(0, 10000)
        session['current_meaning_question_index'] = 0
        session['meaning_correct_count'] = 0
        session['meaning_incorrect_ids'] = []

    if 'meaning_quiz_seed' not in session:
        return redirect(url_for('index'))

    mode = session.get('meaning_quiz_mode')
    questions = get_meanings()
    if not questions:
        message = '言葉が登録されていません。'
        session.clear()
        return render_template('quiz_start_error.html', message=message)

    questions = get_shuffled_data(questions, session['meaning_quiz_seed'])

    current_index = session.get('current_meaning_question_index', 0)
    if current_index >= len(questions):
        correct_count = session.get('meaning_correct_count', 0)
        total_answered = len(questions)
        accuracy = (correct_count / total_answered * 100) if total_answered > 0 else 0
        incorrect_ids = session.get('meaning_incorrect_ids', [])
        
        all_meanings = get_meanings()
        incorrect_questions = [q for q in all_meanings if q['word'] in incorrect_ids]
        session['last_incorrect_questions'] = incorrect_questions

        session.clear()
        return redirect(url_for('quiz_summary', accuracy=f'{accuracy:.2f}', incorrect_count=len(incorrect_questions)))

    meaning_data = questions[current_index]

    all_meanings_for_choices = get_meanings()
    if mode == 'word_to_meaning':
        question, correct_answer = meaning_data['word'], meaning_data['meaning']
        all_answers = [m['meaning'] for m in all_meanings_for_choices]
    else:
        question, correct_answer = meaning_data['meaning'], meaning_data['word']
        all_answers = [m['word'] for m in all_meanings_for_choices]

    choices = generate_choices(all_answers, correct_answer)

    return render_template('meaning_quiz.html', question=question, choices=choices, mode=mode,
                           correct_answer=correct_answer, word_id=meaning_data['word'],
                           current_question_index=current_index + 1,
                           total_questions=len(questions))

@app.route('/meaning_answer', methods=['POST'])
def meaning_answer():
    if 'meaning_quiz_seed' not in session:
        flash('セッションが切れました。もう一度お試しください。', 'error')
        return redirect(url_for('index'))

    user_choice = request.form['choice']
    correct_answer = request.form['correct_answer']
    word_id = request.form['word_id']
    is_correct = (user_choice == correct_answer)

    if is_correct:
        session['meaning_correct_count'] += 1
        flash('正解！', 'success')
    else:
        session.setdefault('meaning_incorrect_ids', []).append(word_id)
        flash(f'不正解... 正解は {correct_answer} でした。', 'error')

    session['current_meaning_question_index'] += 1
    return redirect(url_for('meaning_quiz'))

@app.route('/quiz_summary')
def quiz_summary():
    accuracy = request.args.get('accuracy', '0.00')
    incorrect_count = request.args.get('incorrect_count', 0)
    incorrect_questions = session.get('last_incorrect_questions', [])
    return render_template('quiz_summary.html', accuracy=accuracy, 
                           incorrect_count=incorrect_count, 
                           incorrect_questions=incorrect_questions)



@app.route('/start_all_quiz')
def start_all_quiz():
    session.clear()
    return redirect(url_for('quiz', mode='random'))

@app.route('/edit')
def edit_db():
    words = get_all_data()
    return render_template('edit.html', words=words)

@app.route('/update', methods=['POST'])
def update_db():
    english_words = request.form.getlist('english_full')
    japanese_words = request.form.getlist('japanese_full')
    
    new_words_data = [{'english': eng, 'japanese': jap} for eng, jap in zip(english_words, japanese_words) if eng and jap]
    with open(WORDS_CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['english', 'japanese'])
        for word in new_words_data:
            writer.writerow([word['english'], word['japanese']])

    all_data = get_all_data()
    write_progress_data(all_data)

    session.clear()
    flash('データベースが更新されました。')
    return redirect(url_for('edit_db'))

@app.route('/edit_meanings')
def edit_meanings():
    return render_template('edit_meanings.html', meanings=get_meanings())

@app.route('/update_meanings', methods=['POST'])
def update_meanings():
    # 既存のデータを読み込む
    existing_meanings = get_meanings()
    
    # フォームから送信されたデータを取得
    words = request.form.getlist('word')
    meanings = request.form.getlist('meaning')

    # 更新されたデータのリストを作成
    updated_meanings = []
    for i in range(len(words)):
        # 空の行は無視
        if words[i] and meanings[i]:
            updated_meanings.append({'word': words[i], 'meaning': meanings[i]})

    # 新しい単語（new_word, new_meaning）の処理
    new_words = request.form.getlist('new_word')
    new_meanings = request.form.getlist('new_meaning')
    for i in range(len(new_words)):
        if new_words[i] and new_meanings[i]:
            updated_meanings.append({'word': new_words[i], 'meaning': new_meanings[i]})

    # データを書き込む
    write_meanings(updated_meanings)
    
    flash('言葉の意味データベースが更新されました。')
    return redirect(url_for('edit_meanings'))

if __name__ == '__main__':
    app.run(host='0.0.0.0',port=8080,debug=False)
