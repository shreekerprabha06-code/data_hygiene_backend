import { API_URL } from '../config';

const originalFetch = window.fetch;

window.fetch = async (input, init = {}) => {
  // Only intercept requests to our backend
  if (typeof input === 'string' && input.startsWith(API_URL)) {
    const token = sessionStorage.getItem('jwt_token');
    if (token) {
      init.headers = {
        ...init.headers,
        'Authorization': `Bearer ${token}`
      };
    }
  }
  
  const response = await originalFetch(input, init);
  
  // If the token is invalid or expired, log the user out
  if (response.status === 401 && !input.includes('/login')) {
    sessionStorage.removeItem('jwt_token');
    window.dispatchEvent(new Event('auth-failed'));
  }
  
  return response;
};
