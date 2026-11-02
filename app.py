from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
import json
import os

app = Flask(__name__)
DATA_FILE = 'data.json'
UPLOAD_FOLDER = os.path.join('static', 'avatars')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "tasks": [], "rewards": [], "task_logs": [], "redemptions": [], "cheats": []}
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if "cheats" not in data:
            data["cheats"] = []
        return data

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# --- CÁLCULO DE RACHAS ESTRICTAS ---
def calculate_consecutive_days(dates_list):
    """Calcula días seguidos hasta hoy o ayer. Si no hubo ayer ni hoy, es 0."""
    if not dates_list:
        return 0
    unique_dates = sorted(list(set(dates_list)), reverse=True)
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    
    latest = datetime.strptime(unique_dates[0], '%Y-%m-%d').date()
    if latest < yesterday:
        return 0

    streak = 0
    curr = latest
    for d_str in unique_dates:
        d = datetime.strptime(d_str, '%Y-%m-%d').date()
        if d == curr:
            streak += 1
            curr -= timedelta(days=1)
        else:
            break
    return streak

def get_all_streaks(data, user_id):
    user_logs = [log for log in data['task_logs'] if log['user_id'] == user_id]
    
    # 1. Racha individual por meta
    task_streaks = {}
    for task in data['tasks']:
        tid = task['id']
        t_dates = [log['date'] for log in user_logs if log.get('task_id') == tid]
        task_streaks[tid] = calculate_consecutive_days(t_dates)

    # 2. Racha global de días activos (al menos 1 meta)
    active_dates = [log['date'] for log in user_logs if log.get('task_id') != 'bonus_all_completed']
    global_streak = calculate_consecutive_days(active_dates)

    # 3. Racha de días perfectos (todas las metas completadas sin trampas)
    perfect_dates = [log['date'] for log in user_logs if log.get('task_id') == 'bonus_all_completed']
    perfect_streak = calculate_consecutive_days(perfect_dates)

    return global_streak, perfect_streak, task_streaks

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    username = request.form.get('username', '').strip()
    nickname = request.form.get('nickname', '').strip()
    password = request.form.get('password', '').strip()
    target_str = request.form.get('target', '15').strip()
    
    try:
        target = int(target_str)
    except ValueError:
        target = 15

    if not username or not password or not nickname:
        return jsonify({"error": "Completa todos los campos obligatorios"}), 400

    data = load_data()
    if username in data['users']:
        return jsonify({"error": "Ese usuario ya existe"}), 400

    avatar_path = ""
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename != '':
            ext = os.path.splitext(file.filename)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.heic']:
                filename = f"avatar_{username}{ext}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                avatar_path = f"/static/avatars/{filename}"

    data['users'][username] = {
        "name": nickname,
        "password": password,
        "balance": 0,
        "target": target,
        "avatar": avatar_path
    }
    save_data(data)
    return jsonify({"success": True, "user_id": username, "name": nickname})

@app.route('/api/login', methods=['POST'])
def login():
    payload = request.json
    username = payload.get('username', '').strip()
    password = payload.get('password', '').strip()

    data = load_data()
    user = data['users'].get(username)

    if not user or user.get('password') != password:
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

    return jsonify({"success": True, "user_id": username, "name": user['name']})

@app.route('/api/update-profile', methods=['POST'])
def update_profile():
    current_user_id = request.form.get('current_user_id', '').strip()
    new_username = request.form.get('username', '').strip()
    new_name = request.form.get('name', '').strip()
    new_password = request.form.get('password', '').strip()

    data = load_data()
    if current_user_id not in data['users']:
        return jsonify({"error": "Usuario no encontrado"}), 404

    user = data['users'][current_user_id]
    target_user_id = current_user_id

    if new_username and new_username != current_user_id:
        if new_username in data['users']:
            return jsonify({"error": "Ese usuario ya está ocupado"}), 400
        data['users'][new_username] = user
        del data['users'][current_user_id]
        target_user_id = new_username
        
        for log in data['task_logs']:
            if log['user_id'] == current_user_id:
                log['user_id'] = new_username
        for r in data['redemptions']:
            if r['user_id'] == current_user_id:
                r['user_id'] = new_username

    if new_name:
        data['users'][target_user_id]['name'] = new_name
    if new_password:
        data['users'][target_user_id]['password'] = new_password

    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename != '':
            ext = os.path.splitext(file.filename)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.heic']:
                filename = f"avatar_{target_user_id}{ext}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                data['users'][target_user_id]['avatar'] = f"/static/avatars/{filename}"

    save_data(data)
    return jsonify({
        "success": True, 
        "user_id": target_user_id,
        "name": data['users'][target_user_id]['name'],
        "avatar": data['users'][target_user_id].get('avatar', '')
    })

@app.route('/api/state', methods=['GET'])
def get_state():
    data = load_data()
    user_id = request.args.get('user', '').strip()
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    
    if user_id not in data['users']:
        return jsonify({"error": "Usuario no encontrado"}), 404

    completed_today = [
        log['task_id'] for log in data['task_logs']
        if log['user_id'] == user_id and log['date'] == today_str and log['task_id'] != 'bonus_all_completed'
    ]
    
    user_logs = [log for log in data['task_logs'] if log['user_id'] == user_id]
    perfect_days = [log['date'] for log in user_logs if log['task_id'] == 'bonus_all_completed']
    active_days = list(set(log['date'] for log in user_logs if log['task_id'] != 'bonus_all_completed'))

    global_streak, perfect_streak, task_streaks = get_all_streaks(data, user_id)
    
    # Determinación estricta de la flama en pantalla:
    # - Dorada: 28 días seguidos de TODAS las metas cumplidas
    # - Morada: 7 días seguidos de TODAS las metas cumplidas
    # - Azul: Día perfecto hoy
    # - Naranja: Racha real activa (mínimo 2 días consecutivos)
    flame_type = "none"
    if perfect_streak >= 28:
        flame_type = "dorada"
    elif perfect_streak >= 7:
        flame_type = "morada"
    elif today_str in perfect_days:
        flame_type = "azul"
    elif global_streak >= 2:
        flame_type = "naranja"

    user_data = data['users'][user_id]
    safe_user = {
        "username": user_id,
        "name": user_data["name"],
        "balance": user_data["balance"],
        "target": user_data.get("target", 15),
        "avatar": user_data.get("avatar", ""),
        "streak": global_streak,
        "perfect_streak": perfect_streak,
        "flame_type": flame_type
    }

    return jsonify({
        "user": safe_user,
        "tasks": data['tasks'],
        "rewards": data['rewards'],
        "completed_today": completed_today,
        "task_streaks": task_streaks,
        "active_days": active_days,
        "perfect_days": perfect_days,
        "today_str": today_str
    })

@app.route('/api/toggle-task', methods=['POST'])
def toggle_task():
    payload = request.json
    user_id = payload.get('user_id')
    task_id = payload.get('task_id')
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')

    data = load_data()
    task = next((t for t in data['tasks'] if t['id'] == task_id), None)
    if not task or user_id not in data['users']:
        return jsonify({"error": "Datos inválidos"}), 400

    existing_index = next((
        i for i, log in enumerate(data['task_logs'])
        if log['user_id'] == user_id and log['task_id'] == task_id and log['date'] == today_str
    ), None)

    event_type = "none"

    if existing_index is not None:
        # --- DESMARCAR META ---
        del data['task_logs'][existing_index]
        data['users'][user_id]['balance'] = max(0, data['users'][user_id]['balance'] - task['points'])
        
        # Bandera silenciosa anti-trampas: anula el día perfecto
        cheat_key = f"{user_id}_{today_str}"
        if cheat_key not in data['cheats']:
            data['cheats'].append(cheat_key)

        bonus_index = next((
            i for i, log in enumerate(data['task_logs'])
            if log['user_id'] == user_id and log['task_id'] == 'bonus_all_completed' and log['date'] == today_str
        ), None)
        if bonus_index is not None:
            del data['task_logs'][bonus_index]
            data['users'][user_id]['balance'] = max(0, data['users'][user_id]['balance'] - 1)

        event_type = "unmarked"
    else:
        # --- MARCAR META ---
        data['users'][user_id]['balance'] += task['points']
        data['task_logs'].append({
            "user_id": user_id,
            "task_id": task_id,
            "points": task['points'],
            "date": today_str,
            "timestamp": now.isoformat()
        })

        # Revisar racha de esta meta específica
        user_logs = [log for log in data['task_logs'] if log['user_id'] == user_id and log.get('task_id') == task_id]
        this_task_streak = calculate_consecutive_days([log['date'] for log in user_logs])

        # Solo dispara animación naranja si esta meta ya lleva 2 o más días consecutivos
        if this_task_streak >= 2:
            event_type = "naranja"

        # Verificar si hoy completó el 100% de las metas
        completed_today = [
            log['task_id'] for log in data['task_logs']
            if log['user_id'] == user_id and log['date'] == today_str and log['task_id'] != 'bonus_all_completed'
        ]

        cheat_key = f"{user_id}_{today_str}"
        did_cheat = cheat_key in data['cheats']

        if len(set(completed_today)) == len(data['tasks']) and not did_cheat:
            has_bonus = any(
                log['user_id'] == user_id and log['task_id'] == 'bonus_all_completed' and log['date'] == today_str
                for log in data['task_logs']
            )
            if not has_bonus:
                data['users'][user_id]['balance'] += 1
                data['task_logs'].append({
                    "user_id": user_id,
                    "task_id": "bonus_all_completed",
                    "points": 1,
                    "date": today_str,
                    "timestamp": now.isoformat()
                })
                
                # Evaluar racha perfecta sostenida (7 o 28 días seguidos)
                _, p_streak, _ = get_all_streaks(data, user_id)
                if p_streak >= 28:
                    event_type = "dorada"
                elif p_streak >= 7:
                    event_type = "morada"
                else:
                    event_type = "azul"

    save_data(data)
    return jsonify({
        "success": True, 
        "new_balance": data['users'][user_id]['balance'],
        "event_type": event_type
    })

@app.route('/api/redeem-reward', methods=['POST'])
def redeem_reward():
    payload = request.json
    user_id = payload.get('user_id')
    reward_id = payload.get('reward_id')

    data = load_data()
    reward = next((r for r in data['rewards'] if r['id'] == reward_id), None)
    if not reward or user_id not in data['users']:
        return jsonify({"error": "Datos inválidos"}), 400

    if data['users'][user_id]['balance'] < reward['cost']:
        return jsonify({"error": "Puntos insuficientes"}), 400

    data['users'][user_id]['balance'] -= reward['cost']
    data['redemptions'].append({
        "user_id": user_id,
        "reward_id": reward_id,
        "cost": reward['cost'],
        "timestamp": datetime.now().isoformat()
    })

    save_data(data)
    return jsonify({"success": True, "new_balance": data['users'][user_id]['balance']})

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    scope = request.args.get('scope', 'day')
    data = load_data()
    now = datetime.now()

    scores = {uid: 0 for uid in data['users'].keys()}

    for log in data['task_logs']:
        log_date = datetime.fromisoformat(log['timestamp'])
        matches = False

        if scope == 'day' and log_date.date() == now.date():
            matches = True
        elif scope == 'week' and log_date.isocalendar()[1] == now.isocalendar()[1] and log_date.year == now.year:
            matches = True
        elif scope == 'month' and log_date.month == now.month and log_date.year == now.year:
            matches = True
        elif scope == 'year' and log_date.year == now.year:
            matches = True

        if matches and log['user_id'] in scores:
            scores[log['user_id']] += log['points']

    leaderboard = [
        {
            "user_id": uid, 
            "name": data['users'][uid]['name'], 
            "avatar": data['users'][uid].get('avatar', ''),
            "score": score
        }
        for uid, score in scores.items()
    ]
    leaderboard.sort(key=lambda x: x['score'], reverse=True)

    return jsonify(leaderboard)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)