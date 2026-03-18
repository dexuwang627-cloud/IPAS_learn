let sb = null;
let currentUser = null;
let authMode = 'login';

export function getSupabaseClient() { return sb; }
export function getCurrentUser() { return currentUser; }

export async function initAuth(onReady) {
  // Fetch config from backend (no hardcoded keys)
  try {
    const res = await fetch('/api/v1/config');
    const cfg = await res.json();
    const lib = window.supabase;
    if (lib && lib.createClient && cfg.supabase_url && cfg.supabase_key) {
      sb = lib.createClient(cfg.supabase_url, cfg.supabase_key);
    }
  } catch (e) {
    const el = document.getElementById('auth-error');
    if (el) { el.textContent = 'Failed to load configuration'; el.style.display = 'block'; }
  }

  // Wire up auth buttons
  document.getElementById('btn-auth').addEventListener('click', handleAuth);
  document.getElementById('btn-google').addEventListener('click', googleLogin);
  document.getElementById('btn-logout').addEventListener('click', doLogout);
  document.getElementById('auth-password').addEventListener('keydown', e => {
    if (e.key === 'Enter') handleAuth();
  });

  bootAuth(onReady);
}

function bootAuth(onReady) {
  if (sb) {
    sb.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT') {
        currentUser = null;
        document.getElementById('user-bar').classList.add('hidden');
        document.getElementById('main-app').classList.add('hidden');
        document.getElementById('auth-screen').classList.remove('hidden');
        return;
      }
      if (session?.user) onAuthReady(session.user, onReady);
    });
    sb.auth.getSession().then(({ data }) => {
      if (!data.session) document.getElementById('auth-screen').classList.remove('hidden');
    });
    // Proactive token refresh every 10 minutes
    setInterval(async () => {
      try { await sb.auth.refreshSession(); } catch (e) {}
    }, 10 * 60 * 1000);
  } else {
    document.getElementById('main-app').classList.remove('hidden');
    onReady();
  }
}

function onAuthReady(user, onReady) {
  if (currentUser) return;
  currentUser = user;
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('user-bar').classList.remove('hidden');
  document.getElementById('user-email').textContent = user.email;
  document.getElementById('main-app').classList.remove('hidden');
  onReady();
}

export function toggleAuthMode() {
  authMode = authMode === 'login' ? 'signup' : 'login';
  document.getElementById('auth-title').textContent = authMode === 'login' ? '// LOGIN' : '// SIGN UP';
  document.getElementById('btn-auth').textContent = authMode === 'login' ? 'LOGIN' : 'SIGN UP';
  document.getElementById('auth-toggle').innerHTML = authMode === 'login'
    ? '<a onclick="toggleAuthMode()">註冊</a>'
    : '<a onclick="toggleAuthMode()">登入</a>';
  document.getElementById('auth-error').style.display = 'none';
  document.getElementById('auth-success').style.display = 'none';
}

function showAuthError(msg) {
  const el = document.getElementById('auth-error');
  el.textContent = msg; el.style.display = 'block';
}

async function handleAuth() {
  const email = document.getElementById('auth-email').value.trim();
  const password = document.getElementById('auth-password').value;
  const btn = document.getElementById('btn-auth');
  const succEl = document.getElementById('auth-success');
  document.getElementById('auth-error').style.display = 'none';
  succEl.style.display = 'none';

  if (!sb) { showAuthError('System init failed'); return; }
  if (!email || !password) { showAuthError('Please enter email and password'); return; }
  if (password.length < 6) { showAuthError('Password must be at least 6 characters'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';

  try {
    if (authMode === 'signup') {
      const { data, error } = await sb.auth.signUp({ email, password });
      if (error) throw error;
      if (data.user && !data.session) {
        succEl.textContent = 'Sign up successful! Check your email.';
        succEl.style.display = 'block';
      }
    } else {
      const { error } = await sb.auth.signInWithPassword({ email, password });
      if (error) throw error;
    }
  } catch (e) {
    showAuthError(e.message || 'Auth failed');
  }

  btn.disabled = false;
  btn.textContent = authMode === 'login' ? 'LOGIN' : 'SIGN UP';
}

async function googleLogin() {
  if (!sb) { showAuthError('System init failed'); return; }
  const { error } = await sb.auth.signInWithOAuth({
    provider: 'google',
    options: { redirectTo: window.location.origin + window.location.pathname }
  });
  if (error) showAuthError(error.message);
}

export async function doLogout() {
  if (sb) await sb.auth.signOut();
  currentUser = null;
  document.getElementById('user-bar').classList.add('hidden');
  document.getElementById('main-app').classList.add('hidden');
  document.getElementById('auth-screen').classList.remove('hidden');
}
