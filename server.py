# -*- coding: utf-8 -*-
import sys, os

# Fix for embedded Python — add stdlib zip to path if needed
_here = os.path.dirname(os.path.abspath(__file__))
_py_embed = os.path.join(_here, '..', 'python-embed')
if os.path.exists(_py_embed):
    import glob
    zips = glob.glob(os.path.join(_py_embed, 'python3*.zip'))
    for z in zips:
        if z not in sys.path:
            sys.path.insert(0, z)
    if _py_embed not in sys.path:
        sys.path.insert(0, _py_embed)

import http.server, json, urllib.request, urllib.error, urllib.parse, datetime, re, time, wave, io, socketserver, threading

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ── Load config from .env ─────────────────────────────────────────────────────
def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_path):
        return
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

ANTHROPIC_KEY        = os.environ.get('ANTHROPIC_KEY', '')
# ── Proxy config ──────────────────────────────────────────────────────────────
DEFAULT_PROXY_URL    = 'https://web-production-1f1b0.up.railway.app'  # baked-in default URL
APP_SECRET           = 'Jarvis-2024-XkQ9mR'   # must match Railway APP_SECRET
PROXY_URL            = os.environ.get('PROXY_URL', DEFAULT_PROXY_URL).rstrip('/')
PROXY_CODE           = os.environ.get('PROXY_CODE', '')  # auto-filled after registration
ELEVENLABS_KEY       = os.environ.get('ELEVENLABS_KEY', '')
GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
DEFAULT_SUPABASE_URL = 'https://beeeyljnprimatvzzzze.supabase.co'
DEFAULT_SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJlZWV5bGpucHJpbWF0dnp6enplIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NjI5MTA5OSwiZXhwIjoyMDkxODY3MDk5fQ.f_tvEY59q8pyZNXlmXmM4fMd31bf7NAjMPO5PbmKi1E'
SUPABASE_URL         = os.environ.get('SUPABASE_URL', DEFAULT_SUPABASE_URL).rstrip('/')
SUPABASE_KEY         = os.environ.get('SUPABASE_KEY', DEFAULT_SUPABASE_KEY)
GOOGLE_REDIRECT_URI  = f'http://localhost:{8080}/api/auth/google/callback'
PORT        = 8080
MEMORY_DIR  = 'memories'   # lokální cache
CONV_DIR    = 'conversations'  # lokální cache konverzací
SESSION_FILE = 'session.json'

# Ensure directories exist
os.makedirs(MEMORY_DIR, exist_ok=True)
os.makedirs(CONV_DIR, exist_ok=True)

# ── Speech recognition (optional) ────────────────────────────────────────────
def _try_install(pkg):
    try:
        import subprocess
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', pkg, '--quiet', '--disable-pip-version-check'],
            timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

try:
    import speech_recognition as _sr
    HAS_SR = True
except ImportError:
    print('[STT] SpeechRecognition not found, installing...')
    HAS_SR = _try_install('SpeechRecognition')
    if HAS_SR:
        import speech_recognition as _sr
        print('[STT] SpeechRecognition installed OK')
    else:
        print('[STT] SpeechRecognition install failed — mic transcription unavailable')

# ── Session ───────────────────────────────────────────────────────────────────
def load_session():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {}

def save_session(data):
    with open(SESSION_FILE, 'w') as f:
        json.dump(data, f)

def get_current_user():
    return load_session().get('user')

def get_memory_path(email):
    safe = re.sub(r'[^\w@.-]', '_', email.lower())
    return os.path.join(MEMORY_DIR, f'memory_{safe}.json')

# ── Supabase sync ─────────────────────────────────────────────────────────────
def _supa_headers():
    return {
        'apikey':        SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type':  'application/json',
    }

def supabase_load(email):
    """Načte paměť ze Supabase. Vrátí None při chybě nebo pokud sync není nakonfigurovaný."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        safe_email = urllib.parse.quote(email, safe='')
        url = f'{SUPABASE_URL}/rest/v1/memories?email=eq.{safe_email}&select=data'
        req = urllib.request.Request(url, headers=_supa_headers())
        with urllib.request.urlopen(req, timeout=5) as r:
            rows = json.loads(r.read())
        if rows:
            print(f'  [SYNC] Načtena paměť z cloudu pro {email}')
            return rows[0]['data']
    except Exception as e:
        print(f'  [SYNC] Cloud load selhal: {e}')
    return None

def supabase_save(email, mem):
    """Uloží paměť do Supabase (upsert). Tiše selže pokud sync není nakonfigurovaný."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    try:
        url  = f'{SUPABASE_URL}/rest/v1/memories'
        body = json.dumps({'email': email, 'data': mem, 'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}).encode()
        headers = {**_supa_headers(), 'Prefer': 'resolution=merge-duplicates'}
        req  = urllib.request.Request(url, data=body, headers=headers, method='POST')
        urllib.request.urlopen(req, timeout=5)
        print(f'  [SYNC] Paměť uložena do cloudu pro {email}')
    except Exception as e:
        print(f'  [SYNC] Cloud save selhal: {e}')

# ── Conversation history (Supabase) ──────────────────────────────────────────
def _auto_title(messages):
    for m in messages:
        if m.get('role') == 'user':
            t = m['content'].strip()
            return (t[:47] + '...') if len(t) > 50 else t
    return 'Conversation'

def _conv_path(email):
    safe = re.sub(r'[^\w@.-]', '_', email.lower())
    return os.path.join(CONV_DIR, f'convs_{safe}.json')

def _conv_local_load(email):
    try:
        p = _conv_path(email)
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
    except: pass
    return {}

def _conv_local_save(email, store):
    try:
        with open(_conv_path(email), 'w', encoding='utf-8') as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'  [HIST] local write failed: {e}')

def conv_list(email):
    store = _conv_local_load(email)
    rows  = list(store.values())
    rows.sort(key=lambda r: r.get('updated_at',''), reverse=True)
    return [{'id': r['id'], 'title': r.get('title',''), 'updated_at': r.get('updated_at','')} for r in rows[:50]]

def conv_load(conv_id, email):
    store = _conv_local_load(email)
    return store.get(conv_id)

def conv_save(email, conv_id, title, messages):
    import uuid
    store = _conv_local_load(email)
    now   = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if not conv_id or conv_id not in store:
        conv_id = str(uuid.uuid4())
    store[conv_id] = {
        'id': conv_id, 'user_email': email,
        'title': title, 'messages': messages, 'updated_at': now
    }
    _conv_local_save(email, store)
    # Volitelně synchronizuj do Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            data = json.dumps({'user_email': email, 'title': title,
                               'messages': messages, 'updated_at': now}).encode()
            hdrs = {**_supa_headers(), 'Prefer': 'return=representation,resolution=merge-duplicates'}
            existing = store[conv_id].get('supa_id')
            if existing:
                url = f'{SUPABASE_URL}/rest/v1/conversations?id=eq.{urllib.parse.quote(existing,safe="")}'
                req = urllib.request.Request(url, data=data, headers=hdrs, method='PATCH')
            else:
                url = f'{SUPABASE_URL}/rest/v1/conversations'
                req = urllib.request.Request(url, data=data, headers=hdrs, method='POST')
            with urllib.request.urlopen(req, timeout=5) as r:
                result = json.loads(r.read())
            row = (result[0] if isinstance(result, list) else result) or {}
            if row.get('id'):
                store[conv_id]['supa_id'] = row['id']
                _conv_local_save(email, store)
        except Exception as e:
            print(f'  [HIST] supabase sync failed (ok): {e}')
    return conv_id

def conv_delete(conv_id, email):
    store = _conv_local_load(email)
    if conv_id not in store:
        return False
    supa_id = store[conv_id].get('supa_id')
    del store[conv_id]
    _conv_local_save(email, store)
    if supa_id and SUPABASE_URL and SUPABASE_KEY:
        try:
            url = (f'{SUPABASE_URL}/rest/v1/conversations'
                   f'?id=eq.{urllib.parse.quote(supa_id,safe="")}')
            urllib.request.urlopen(urllib.request.Request(url, headers=_supa_headers(), method='DELETE'), timeout=5)
        except: pass
    return True

# ── Memory ────────────────────────────────────────────────────────────────────
def load_memory(email=None):
    if not email:
        user = get_current_user()
        email = user.get('email') if user else None

    # 1. Zkus cloud
    if email:
        cloud = supabase_load(email)
        if cloud is not None:
            # Ulož lokálně jako cache
            _save_local(cloud, email)
            return cloud

    # 2. Fallback na lokální cache
    path = get_memory_path(email) if email else 'memory.json'
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass

    return {'profile':{}, 'preferences':{}, 'tasks':[], 'facts':[], 'history':[]}

def _save_local(mem, email):
    """Uloží paměť pouze lokálně (interní helper)."""
    path = get_memory_path(email) if email else 'memory.json'
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except: pass

def save_memory(mem, email=None):
    if not email:
        user = get_current_user()
        email = user.get('email') if user else None
    path = get_memory_path(email) if email else 'memory.json'
    # Vždy ulož lokálně
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)
    # Asynchronně ulož do cloudu
    if email:
        supabase_save(email, mem)

def memory_to_prompt(mem):
    parts = []
    if mem.get('profile'):
        parts.append('USER PROFILE: ' + ', '.join(f'{k}={v}' for k,v in mem['profile'].items()))
    if mem.get('preferences'):
        parts.append('PREFERENCES: ' + ', '.join(f'{k}={v}' for k,v in mem['preferences'].items()))
    if mem.get('facts'):
        parts.append('KNOWN FACTS: ' + ' | '.join(mem['facts'][-20:]))
    if mem.get('tasks'):
        open_tasks = [t for t in mem['tasks'] if not t.get('done')]
        if open_tasks:
            parts.append('PENDING TASKS: ' + ' | '.join(
                f"[{t.get('due','')}] {t['text']}" for t in open_tasks[-10:]))
    if mem.get('history'):
        parts.append('PAST CONVERSATIONS: ' + ' | '.join(mem['history'][-5:]))
    return '\n'.join(parts)

def apply_memory_blocks(text):
    blocks = re.findall(r'<memory>(.*?)</memory>', text, re.DOTALL)
    if not blocks: return text
    mem = load_memory()
    for block in blocks:
        try:
            d = json.loads(block.strip())
            if 'profile'     in d: mem['profile'].update(d['profile'])
            if 'preferences' in d: mem['preferences'].update(d['preferences'])
            if 'fact'        in d:
                f = d['fact'].strip()
                if f and f not in mem['facts']: mem['facts'].append(f)
            if 'task'        in d:
                t = d['task']
                t['created'] = datetime.datetime.now().isoformat()[:16]
                t.setdefault('done', False)
                mem['tasks'].append(t)
        except: pass
    save_memory(mem)
    return re.sub(r'\s*<memory>.*?</memory>', '', text, flags=re.DOTALL).strip()

# ── Web search via DuckDuckGo ─────────────────────────────────────────────────
def web_search(query, max_results=5):
    try:
        q   = urllib.parse.quote_plus(query)
        url = f'https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1'
        req = urllib.request.Request(url, headers={'User-Agent': 'JADE/1.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())

        results = []

        # Abstract (best single answer)
        if data.get('AbstractText'):
            results.append(f"[{data.get('AbstractSource','')}] {data['AbstractText']}")

        # Answer (instant answer)
        if data.get('Answer'):
            results.append(f"[Answer] {data['Answer']}")

        # Related topics
        for topic in data.get('RelatedTopics', [])[:max_results]:
            if isinstance(topic, dict) and topic.get('Text'):
                results.append(topic['Text'])

        if results:
            return '\n'.join(results[:max_results])

        # Fallback: HTML scrape of DuckDuckGo
        return ddg_html_search(query, max_results)

    except Exception as e:
        return ddg_html_search(query, max_results)

def ddg_html_search(query, max_results=5):
    try:
        q   = urllib.parse.quote_plus(query)
        url = f'https://html.duckduckgo.com/html/?q={q}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode('utf-8', errors='ignore')

        # Extract result snippets
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        titles   = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)

        results = []
        for i, (t, s) in enumerate(zip(titles, snippets)):
            if i >= max_results: break
            t = re.sub(r'<[^>]+>', '', t).strip()
            s = re.sub(r'<[^>]+>', '', s).strip()
            if t and s:
                results.append(f"• {t}: {s}")

        return '\n'.join(results) if results else 'No results found.'
    except Exception as e:
        return f'Search failed: {e}'

# ── System prompt builder ─────────────────────────────────────────────────────
SEARCH_INSTRUCTIONS = """

INTERNET ACCESS INSTRUCTIONS:
You have real-time internet access via web search. When the user asks about:
- Current news, weather, prices, scores, events
- Facts you are uncertain about
- Anything that may have changed recently
- Explicit requests to "search", "look up", "find", "what is the latest"

You MUST use this format to trigger a search (on its own line):
<search>your search query here</search>

The search results will be provided to you automatically. Then give your answer based on those results.
You can search multiple times if needed. Always tell the user what you searched for.
"""

MEM_INSTRUCTIONS = """

MEMORY INSTRUCTIONS: When the user shares personal info (name, age, location, habits,
preferences, tasks, reminders), silently append ONE JSON block at the very end of your reply:
<memory>{"profile":{"name":"..."},"fact":"...","task":{"text":"...","due":"..."}}</memory>
Only include keys that have NEW information. Omit the block if nothing new was learned.
The user will never see this block — it is stripped automatically."""

def build_system(base_system, mem):
    mem_str   = memory_to_prompt(mem)
    mem_block = ('\n\n--- JADE MEMORY ---\n' + mem_str + '\n--- END MEMORY ---') if mem_str else ''
    return base_system + mem_block + SEARCH_INSTRUCTIONS + MEM_INSTRUCTIONS

def proxy_register(email: str) -> bool:
    """Auto-register email with proxy server. Saves code to .env. Returns True on success."""
    global PROXY_CODE
    url = PROXY_URL.rstrip('/')
    if not url or url == 'REPLACE_WITH_YOUR_RAILWAY_URL':
        return False
    try:
        payload = json.dumps({'email': email}).encode()
        req = urllib.request.Request(
            f'{url}/api/register',
            data=payload,
            method='POST',
            headers={
                'Content-Type':  'application/json',
                'X-App-Secret':  APP_SECRET,
            }
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            code = data.get('code', '')
            if not code:
                return False
            # Save to .env
            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
            lines = []
            if os.path.exists(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            found = False
            for i, line in enumerate(lines):
                if line.startswith('PROXY_CODE='):
                    lines[i] = f'PROXY_CODE={code}\n'
                    found = True; break
            if not found:
                lines.append(f'PROXY_CODE={code}\n')
            with open(env_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            os.environ['PROXY_CODE'] = code
            PROXY_CODE = code
            print(f'[PROXY] Registered {email} — code saved')
            return True
    except Exception as e:
        print(f'[PROXY] Registration failed: {e}')
        return False

def _anthropic_url():
    """Returns (url, headers) — uses proxy if configured, otherwise direct Anthropic."""
    if PROXY_URL and PROXY_CODE:
        return (
            f'{PROXY_URL}/v1/messages',
            {
                'Content-Type':  'application/json',
                'X-Access-Code': PROXY_CODE,
            }
        )
    return (
        'https://api.anthropic.com/v1/messages',
        {
            'Content-Type':      'application/json',
            'x-api-key':         ANTHROPIC_KEY,
            'anthropic-version': '2023-06-01',
        }
    )

def _reregister_proxy():
    """Pokud proxy vrátí invalid code, smaž kód a znovu zaregistruj."""
    global PROXY_CODE
    session = load_session()
    email = session.get('user', {}).get('email', '')
    if not email:
        return False
    print('[PROXY] Access code invalid — re-registering...')
    PROXY_CODE = ''
    # Smaž z .env
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(l for l in lines if not l.startswith('PROXY_CODE='))
    os.environ.pop('PROXY_CODE', None)
    return proxy_register(email)

def _is_invalid_code_error(e):
    """Detekuje chybu 'Invalid or inactive access code' z proxy."""
    try:
        body = json.loads(e.read())
        return 'invalid' in body.get('error', '').lower() or 'inactive' in body.get('error', '').lower()
    except:
        return False

def call_anthropic(payload):
    for attempt in range(2):
        url, headers = _anthropic_url()
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=headers, method='POST'
        )
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0 and PROXY_CODE:
                if _is_invalid_code_error(e):
                    if _reregister_proxy():
                        continue  # retry with new code
            raise

def stream_anthropic(payload):
    """Generátor: vrací textové chunky ze streaming Anthropic API."""
    for attempt in range(2):
        p = {**payload, 'stream': True}
        url, headers = _anthropic_url()
        req = urllib.request.Request(
            url, data=json.dumps(p).encode(), headers=headers, method='POST'
        )
        try:
            with urllib.request.urlopen(req) as resp:
                for raw in resp:
                    line = raw.decode('utf-8').rstrip('\r\n')
                    if not line.startswith('data: '):
                        continue
                    ds = line[6:]
                    if ds == '[DONE]':
                        break
                    try:
                        ev = json.loads(ds)
                        if ev.get('type') == 'content_block_delta':
                            text = ev.get('delta', {}).get('text', '')
                            if text:
                                yield text
                    except:
                        pass
            return  # úspěch — konec generátoru
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0 and PROXY_CODE:
                if _is_invalid_code_error(e):
                    if _reregister_proxy():
                        continue  # retry s novým kódem
            raise

# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {args[0]} {args[1]}")

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code); self._cors()
        self.send_header('Content-Type', 'application/json')
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        # ── Auth: Google URL ──────────────────────────────────────────────────
        if self.path == '/api/auth/google-url':
            params = urllib.parse.urlencode({
                'client_id':     GOOGLE_CLIENT_ID,
                'redirect_uri':  GOOGLE_REDIRECT_URI,
                'response_type': 'code',
                'scope':         'openid email profile',
                'access_type':   'offline',
                'prompt':        'select_account'
            })
            url = f'https://accounts.google.com/o/oauth2/v2/auth?{params}'
            self.send_json(200, {'url': url})

        # ── Auth: Google callback ─────────────────────────────────────────────
        elif self.path.startswith('/api/auth/google/callback'):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            code   = params.get('code', [None])[0]
            if not code:
                self._respond(400, 'text/html', b'<h1>Auth failed</h1>')
                return
            try:
                # Exchange code for tokens
                token_data = urllib.parse.urlencode({
                    'code': code, 'client_id': GOOGLE_CLIENT_ID,
                    'client_secret': GOOGLE_CLIENT_SECRET,
                    'redirect_uri': GOOGLE_REDIRECT_URI,
                    'grant_type': 'authorization_code'
                }).encode()
                req = urllib.request.Request(
                    'https://oauth2.googleapis.com/token',
                    data=token_data,
                    headers={'Content-Type':'application/x-www-form-urlencoded'})
                with urllib.request.urlopen(req) as r:
                    tokens = json.loads(r.read())
                # Get user info
                req2 = urllib.request.Request(
                    'https://www.googleapis.com/oauth2/v2/userinfo',
                    headers={'Authorization': f'Bearer {tokens["access_token"]}'})
                with urllib.request.urlopen(req2) as r:
                    guser = json.loads(r.read())
                user = {'email': guser['email'], 'name': guser.get('name',''), 'picture': guser.get('picture','')}
                mem  = load_memory(user['email'])
                is_new = not mem.get('profile')
                save_session({'user': user, 'authenticated': True})
                html = b'<html><body style="background:#020810;color:#00d4ff;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh"><h2>IDENTITY CONFIRMED. You may close this window.</h2></body></html>'
                self._respond(200, 'text/html', html)
            except Exception as e:
                self._respond(500, 'text/html', f'<h1>Error: {e}</h1>'.encode())

        # ── Auth: Status ──────────────────────────────────────────────────────
        elif self.path == '/api/auth/status':
            session = load_session()
            if session.get('authenticated') and session.get('user'):
                user  = session['user']
                email = user.get('email','')
                mem   = load_memory(email)
                is_new = not mem.get('profile')
                self.send_json(200, {'authenticated': True, 'user': user, 'isNewUser': is_new, 'memory': mem})
            else:
                self.send_json(200, {'authenticated': False})

        # ── Config read (masked keys) ─────────────────────────────────────────
        elif self.path == '/api/config':
            def mask(v): return (v[:8] + '...' + v[-4:]) if len(v) > 14 else ('*' * len(v) if v else '')
            proxy_url  = os.environ.get('PROXY_URL', '')
            proxy_code = os.environ.get('PROXY_CODE', '')
            self.send_json(200, {
                'anthropic_set':  bool(os.environ.get('ANTHROPIC_KEY')),
                'elevenlabs_set': bool(os.environ.get('ELEVENLABS_KEY')),
                'supabase_set':   bool(os.environ.get('SUPABASE_URL')),
                'anthropic_mask': mask(os.environ.get('ANTHROPIC_KEY', '')),
                'proxy_set':      bool(proxy_url and proxy_code),
                'proxy_url':      proxy_url,
                'proxy_code_set': bool(proxy_code),
                'proxy_code_mask': mask(proxy_code),
            })

        # ── Memory read ───────────────────────────────────────────────────────
        elif self.path == '/api/memory':
            self.send_json(200, load_memory())

        # ── Conversation history: list ────────────────────────────────────────
        elif self.path == '/api/conversations':
            user = get_current_user()
            email = user.get('email') if user else None
            if not email: self.send_json(401, {'error': 'Not authenticated'})
            else: self.send_json(200, {'conversations': conv_list(email)})

        # ── Conversation history: load ────────────────────────────────────────
        elif self.path.startswith('/api/conversations/load/'):
            user = get_current_user()
            email = user.get('email') if user else None
            conv_id = self.path.split('/')[-1]
            if not email: self.send_json(401, {'error': 'Not authenticated'})
            else:
                row = conv_load(conv_id, email)
                self.send_json(200, row) if row else self.send_json(404, {'error': 'Not found'})

        # ── Static HTML/JS/CSS — vždy bez cache ──────────────────────────────
        elif self.path.split('?')[0].endswith(('.html', '.js', '.css')):
            import mimetypes
            clean = self.path.split('?')[0].lstrip('/')
            fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), clean)
            if os.path.isfile(fpath):
                with open(fpath, 'rb') as fh:
                    data = fh.read()
                ctype = mimetypes.guess_type(fpath)[0] or 'text/plain'
                self.send_response(200); self._cors()
                self.send_header('Content-Type', ctype + '; charset=utf-8')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)
            else:
                super().do_GET()

        else:
            super().do_GET()

    def _respond(self, code, ctype, body):
        self.send_response(code); self._cors()
        self.send_header('Content-Type', ctype)
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        global ANTHROPIC_KEY, SUPABASE_URL, SUPABASE_KEY, PROXY_URL, PROXY_CODE
        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length)

        # ── Auth: Email login ─────────────────────────────────────────────────
        if self.path == '/api/auth/email':
            try:
                data  = json.loads(body)
                email = data.get('email','').lower().strip()
                mem   = load_memory(email)
                is_new = not mem.get('profile')
                name  = mem.get('profile',{}).get('firstname', email.split('@')[0])
                user  = {'email': email, 'name': name, 'picture': ''}
                save_session({'user': user, 'authenticated': True})
                # Auto-register with proxy in background (only if no code yet)
                if not PROXY_CODE:
                    import threading
                    threading.Thread(target=proxy_register, args=(email,), daemon=True).start()
                self.send_json(200, {'ok': True, 'isNewUser': is_new, 'name': name, 'memory': mem})
            except Exception as e:
                self.send_json(400, {'error': str(e)})

        # ── Auth: Session ─────────────────────────────────────────────────────
        elif self.path == '/api/auth/session':
            try:
                data  = json.loads(body)
                email = data.get('email','').lower().strip()
                mem   = load_memory(email)
                user  = get_current_user() or {'email': email, 'name': email.split('@')[0], 'picture': ''}
                save_session({'user': user, 'authenticated': True})
                self.send_json(200, {'ok': True})
            except Exception as e:
                self.send_json(400, {'error': str(e)})

        # ── Auth: Onboarding ──────────────────────────────────────────────────
        elif self.path == '/api/auth/onboard':
            try:
                data  = json.loads(body)
                email = data.get('email','').lower().strip()
                mem   = data.get('memory', {})
                save_memory(mem, email)
                # Update session name
                session = load_session()
                if session.get('user'):
                    session['user']['name'] = mem.get('profile',{}).get('firstname', session['user'].get('name',''))
                    save_session(session)
                self.send_json(200, {'ok': True})
            except Exception as e:
                self.send_json(400, {'error': str(e)})

        # ── Auth: Logout ──────────────────────────────────────────────────────
        elif self.path == '/api/auth/logout':
            save_session({})
            self.send_json(200, {'ok': True})

        # ── Manuální cloud sync ───────────────────────────────────────────────
        elif self.path == '/api/sync':
            user  = get_current_user()
            email = user.get('email') if user else None
            if not email:
                self.send_json(401, {'error': 'Not logged in'})
            elif not SUPABASE_URL or not SUPABASE_KEY:
                self.send_json(503, {'error': 'Cloud sync not configured'})
            else:
                try:
                    cloud = supabase_load(email)
                    if cloud is not None:
                        _save_local(cloud, email)
                        self.send_json(200, {'ok': True, 'source': 'cloud', 'memory': cloud})
                    else:
                        # Cloud nemá data — push lokální data do cloudu
                        mem = load_memory(email)
                        supabase_save(email, mem)
                        self.send_json(200, {'ok': True, 'source': 'local', 'memory': mem})
                except Exception as e:
                    self.send_json(500, {'error': str(e)})

        # ── Config write (save API keys to .env) ─────────────────────────────
        elif self.path == '/api/config':
            try:
                data = json.loads(body)
                env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
                # Read existing .env
                lines = []
                if os.path.exists(env_path):
                    with open(env_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                # Update or add keys
                key_map = {
                    'ANTHROPIC_KEY':   data.get('anthropic_key', '').strip(),
                    'ELEVENLABS_KEY':  data.get('elevenlabs_key', '').strip(),
                    'SUPABASE_URL':    data.get('supabase_url', '').strip(),
                    'SUPABASE_KEY':    data.get('supabase_key', '').strip(),
                    'PROXY_URL':       data.get('proxy_url', '').strip().rstrip('/'),
                    'PROXY_CODE':      data.get('proxy_code', '').strip(),
                }
                for key, val in key_map.items():
                    if not val:
                        continue  # skip empty — don't overwrite existing
                    found = False
                    for i, line in enumerate(lines):
                        if line.startswith(key + '='):
                            lines[i] = f'{key}={val}\n'
                            found = True; break
                    if not found:
                        lines.append(f'{key}={val}\n')
                    os.environ[key] = val  # apply immediately without restart
                with open(env_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                # Reload globals
                ANTHROPIC_KEY = os.environ.get('ANTHROPIC_KEY', '')
                SUPABASE_URL  = os.environ.get('SUPABASE_URL', DEFAULT_SUPABASE_URL).rstrip('/')
                SUPABASE_KEY  = os.environ.get('SUPABASE_KEY', DEFAULT_SUPABASE_KEY)
                PROXY_URL     = os.environ.get('PROXY_URL', DEFAULT_PROXY_URL).rstrip('/')
                PROXY_CODE    = os.environ.get('PROXY_CODE', '')
                self.send_json(200, {'ok': True})
            except Exception as e:
                self.send_json(400, {'error': str(e)})

        # ── Memory write ──────────────────────────────────────────────────────
        elif self.path == '/api/memory':
            try:
                data = json.loads(body)
                mem  = load_memory()
                if 'profile'     in data: mem['profile'].update(data['profile'])
                if 'preferences' in data: mem['preferences'].update(data['preferences'])
                if 'fact'        in data:
                    f = data['fact'].strip()
                    if f and f not in mem['facts']: mem['facts'].append(f)
                if 'task'        in data:
                    t = data['task']
                    t['created'] = datetime.datetime.now().isoformat()[:16]
                    t.setdefault('done', False)
                    mem['tasks'].append(t)
                if 'complete_task' in data:
                    idx = data['complete_task']
                    if 0 <= idx < len(mem['tasks']): mem['tasks'][idx]['done'] = True
                if 'summary'     in data:
                    mem['history'].append(data['summary'])
                    mem['history'] = mem['history'][-50:]
                save_memory(mem)
                self.send_json(200, {'ok': True, 'memory': mem})
            except Exception as e:
                self.send_json(400, {'error': str(e)})

        # ── Conversation history: save ────────────────────────────────────────
        elif self.path == '/api/conversations/save':
            user = get_current_user()
            email = user.get('email') if user else None
            if not email: self.send_json(401, {'error': 'Not authenticated'})
            else:
                try:
                    data     = json.loads(body)
                    messages = data.get('messages', [])
                    title    = data.get('title') or _auto_title(messages)
                    conv_id  = data.get('id')
                    new_id   = conv_save(email, conv_id, title, messages)
                    self.send_json(200, {'ok': True, 'id': new_id})
                except Exception as e:
                    self.send_json(400, {'error': str(e)})

        # ── Conversation history: delete ──────────────────────────────────────
        elif self.path.startswith('/api/conversations/delete/'):
            user = get_current_user()
            email = user.get('email') if user else None
            conv_id = self.path.split('/')[-1]
            if not email: self.send_json(401, {'error': 'Not authenticated'})
            else:
                ok = conv_delete(conv_id, email)
                self.send_json(200 if ok else 500, {'ok': ok})

        # ── Clear all conversations ───────────────────────────────────────────
        elif self.path == '/api/conversations/clear':
            user = get_current_user()
            email = user.get('email') if user else None
            if not email:
                self.send_json(401, {'error': 'Not authenticated'})
            else:
                try:
                    store = _conv_local_load(email)
                    for conv_id in list(store.keys()):
                        conv_delete(conv_id, email)
                    # Also clear cloud if available
                    if SUPABASE_URL and SUPABASE_KEY:
                        try:
                            req = urllib.request.Request(
                                f'{SUPABASE_URL}/rest/v1/conversations?user_email=eq.{urllib.parse.quote(email)}',
                                method='DELETE',
                                headers={'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}
                            )
                            urllib.request.urlopen(req, timeout=5)
                        except: pass
                    self.send_json(200, {'ok': True})
                except Exception as e:
                    self.send_json(500, {'error': str(e)})

        # ── Clear memory ──────────────────────────────────────────────────────
        elif self.path == '/api/memory/clear':
            user = get_current_user()
            email = user.get('email') if user else None
            if not email:
                self.send_json(401, {'error': 'Not authenticated'})
            else:
                try:
                    save_memory({}, email)
                    self.send_json(200, {'ok': True})
                except Exception as e:
                    self.send_json(500, {'error': str(e)})

        # ── Chat with search loop ─────────────────────────────────────────────
        elif self.path == '/api/chat':
            try:
                payload = json.loads(body)
                mem     = load_memory()
                payload['system'] = build_system(payload.get('system',''), mem)

                # Agentic loop: up to 4 search rounds
                for attempt in range(4):
                    resp = call_anthropic(payload)
                    text = resp.get('content', [{}])[0].get('text', '')

                    search_tags = re.findall(r'<search>(.*?)</search>', text, re.DOTALL)
                    if not search_tags:
                        break  # No more searches needed

                    # Execute searches and feed results back
                    search_results_block = ''
                    for query in search_tags:
                        query = query.strip()
                        print(f"  [SEARCH] {query}")
                        results = web_search(query)
                        search_results_block += f'\n\n[SEARCH: "{query}"]\n{results}'

                    # Append search results as a tool result message
                    visible_text = re.sub(r'<search>.*?</search>', '', text, flags=re.DOTALL).strip()
                    payload['messages'].append({'role': 'assistant', 'content': visible_text or '...'})
                    payload['messages'].append({
                        'role': 'user',
                        'content': f'[SEARCH RESULTS]{search_results_block}\n\n[END SEARCH RESULTS]\nNow answer based on these results.'
                    })

                # Final text cleanup
                final_text = resp.get('content', [{}])[0].get('text', '')
                final_text = re.sub(r'<search>.*?</search>', '', final_text, flags=re.DOTALL).strip()
                final_text = apply_memory_blocks(final_text)

                resp['content'][0]['text'] = final_text
                self.send_json(200, resp)

            except urllib.error.HTTPError as e:
                err = json.loads(e.read())
                self.send_json(e.code, err)

        # ── Chat streaming ────────────────────────────────────────────────────
        elif self.path == '/api/chat/stream':
            try:
                payload = json.loads(body)
                mem     = load_memory()
                payload['system'] = build_system(payload.get('system', ''), mem)

                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('X-Accel-Buffering', 'no')
                self.end_headers()

                def sse(obj):
                    try:
                        line = 'data: ' + json.dumps(obj, ensure_ascii=False) + '\n\n'
                        self.wfile.write(line.encode('utf-8'))
                        self.wfile.flush()
                    except: pass

                GUARD       = 15   # buffer pro detekci částečných tagů
                accumulated = ''
                sent_pos    = 0
                search_hit  = False
                memory_hit  = False

                # ── Fáze 1: streamuj první odpověď, detekuj <search>/<memory> ──
                for chunk in stream_anthropic(payload):
                    accumulated += chunk
                    if search_hit or memory_hit:
                        continue

                    # Detekce <search>
                    search_idx = accumulated.find('<search>', sent_pos)
                    if search_idx != -1:
                        # Pošli text před tagem, pak přeruš
                        if search_idx > sent_pos:
                            sse({'t': accumulated[sent_pos:search_idx]})
                        search_hit = True
                        continue

                    # Detekce <memory>
                    mem_idx = accumulated.find('<memory>', sent_pos)
                    if mem_idx != -1:
                        if mem_idx > sent_pos:
                            sse({'t': accumulated[sent_pos:mem_idx]})
                            sent_pos = mem_idx
                        memory_hit = True
                        continue

                    # Pošli bezpečnou část (drž posledních GUARD znaků)
                    safe_end = max(sent_pos, len(accumulated) - GUARD)
                    if safe_end > sent_pos:
                        sse({'t': accumulated[sent_pos:safe_end]})
                        sent_pos = safe_end

                # ── Po skončení streamu: dopláchni zbytek ──────────────────────
                if not search_hit:
                    tail = accumulated[sent_pos:]
                    m = tail.find('<memory>')
                    if m != -1:
                        if m > 0:
                            sse({'t': tail[:m]})
                        apply_memory_blocks(accumulated)
                    else:
                        if tail:
                            sse({'t': tail})
                        apply_memory_blocks(accumulated)

                # ── Fáze 2: pokud byl nalezen <search>, proveď search loop ─────
                if search_hit:
                    sse({'searching': True})

                    # Pokud stream skončil uprostřed tagu, dokončíme non-streaming
                    tags = re.findall(r'<search>(.*?)</search>', accumulated, re.DOTALL)
                    if not tags:
                        resp_full = call_anthropic(payload)
                        accumulated = resp_full['content'][0]['text']
                        tags = re.findall(r'<search>(.*?)</search>', accumulated, re.DOTALL)

                    for attempt in range(4):
                        # Proveď vyhledávání
                        sr = ''
                        for q in tags:
                            q = q.strip()
                            print(f'  [SEARCH] {q}')
                            sr += f'\n[SEARCH: "{q}"]\n{web_search(q)}'

                        visible = re.sub(r'<search>.*?</search>', '', accumulated, flags=re.DOTALL).strip()
                        payload['messages'].append({'role': 'assistant', 'content': visible or '...'})
                        payload['messages'].append({'role': 'user', 'content': f'[SEARCH RESULTS]{sr}\n\n[END SEARCH RESULTS]\nNow answer based on these results.'})

                        # Získej další odpověď
                        resp = call_anthropic(payload)
                        accumulated = resp['content'][0]['text']
                        tags = re.findall(r'<search>(.*?)</search>', accumulated, re.DOTALL)

                        if not tags:
                            # Finální odpověď — simuluj stream slovo po slovu
                            final = apply_memory_blocks(re.sub(r'<search>.*?</search>', '', accumulated, flags=re.DOTALL).strip())
                            words = final.split(' ')
                            for i, w in enumerate(words):
                                sse({'t': w + ('' if i == len(words) - 1 else ' ')})
                                time.sleep(0.018)
                            break

                sse({'done': True})

            except urllib.error.HTTPError as e:
                try:
                    sse({'error': json.loads(e.read())})
                except:
                    sse({'error': {'message': str(e)}})
            except Exception as e:
                try:
                    sse({'error': {'message': str(e)}})
                except: pass

        # ── Search endpoint (direct) ──────────────────────────────────────────
        elif self.path == '/api/search':
            try:
                data    = json.loads(body)
                query   = data.get('query', '')
                results = web_search(query)
                self.send_json(200, {'query': query, 'results': results})
            except Exception as e:
                self.send_json(400, {'error': str(e)})

        # ── ElevenLabs proxy ──────────────────────────────────────────────────
        elif self.path.startswith('/api/tts/'):
            voice_id = self.path.split('/')[-1]
            try:
                req = urllib.request.Request(
                    f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}',
                    data=body,
                    headers={'Content-Type':'application/json','xi-api-key':ELEVENLABS_KEY},
                    method='POST')
                with urllib.request.urlopen(req) as r:
                    audio = r.read()
                self.send_response(200); self._cors()
                self.send_header('Content-Type', 'audio/mpeg')
                self.end_headers(); self.wfile.write(audio)
            except urllib.error.HTTPError as e:
                self.send_response(e.code); self._cors()
                self.end_headers(); self.wfile.write(e.read())

        # ── Speech-to-Text ────────────────────────────────────────────────────────
        elif self.path.startswith('/api/stt'):
            if not HAS_SR:
                self.send_json(503, {'error': 'SpeechRecognition not installed. Restart app to auto-install.'})
                return
            import tempfile, subprocess as _sp
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            lang   = params.get('lang', ['cs-CZ'])[0]
            ctype  = self.headers.get('Content-Type', 'audio/webm')

            # Ulož přijatý audio do dočasného souboru
            suffix = '.wav' if 'wav' in ctype else '.webm' if 'webm' in ctype else '.ogg'
            tmp_in = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp_in.write(body); tmp_in.close()

            wav_path = tmp_in.name
            try:
                # Pokud není WAV, zkus převést přes ffmpeg
                if suffix != '.wav':
                    wav_path = tmp_in.name.replace(suffix, '.wav')
                    r = _sp.run(
                        ['ffmpeg', '-y', '-i', tmp_in.name, '-ar', '16000', '-ac', '1', wav_path],
                        capture_output=True, timeout=15)
                    if r.returncode != 0:
                        raise RuntimeError('ffmpeg failed: ' + r.stderr.decode(errors='ignore')[:200])

                with wave.open(wav_path) as wf:
                    rate   = wf.getframerate()
                    width  = wf.getsampwidth()
                    frames = wf.readframes(wf.getnframes())

                recognizer = _sr.Recognizer()
                audio_data = _sr.AudioData(frames, rate, width)
                text = recognizer.recognize_google(audio_data, language=lang)
                self.send_json(200, {'transcript': text})

            except _sr.UnknownValueError:
                self.send_json(200, {'transcript': ''})
            except _sr.RequestError as e:
                self.send_json(503, {'error': f'STT service: {e}'})
            except Exception as e:
                self.send_json(500, {'error': str(e)})
            finally:
                for p in set([tmp_in.name, wav_path]):
                    try: os.unlink(p)
                    except: pass

        else:
            self.send_response(404); self.end_headers()

os.chdir(os.path.dirname(os.path.abspath(__file__)))
print(f"\n  J.A.R.V.I.S. server  ->  http://localhost:{PORT}/jade.html")
print(f"  Memory dir           ->  {os.path.abspath(MEMORY_DIR)}")
print(f"  Web search           ->  DuckDuckGo (no API key needed)\n")
class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

ThreadedHTTPServer(('', PORT), Handler).serve_forever()
