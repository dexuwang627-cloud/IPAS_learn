import { getSupabaseClient } from './auth.js';
import { doLogout } from './auth.js';

export async function getAuthHeaders() {
  const sb = getSupabaseClient();
  if (!sb) return { 'Content-Type': 'application/json' };
  const { data } = await sb.auth.getSession();
  const token = data?.session?.access_token || '';
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': 'Bearer ' + token } : {}),
  };
}

export async function authFetch(url, options = {}) {
  const headers = await getAuthHeaders();
  const res = await fetch(url, { ...options, headers: { ...headers, ...options.headers } });
  if (res.status === 401) {
    const sb = getSupabaseClient();
    if (sb) {
      const { error } = await sb.auth.refreshSession();
      if (error) return res;
      const retryHeaders = await getAuthHeaders();
      const retry = await fetch(url, { ...options, headers: { ...retryHeaders, ...options.headers } });
      return retry;
    }
  }
  return res;
}
