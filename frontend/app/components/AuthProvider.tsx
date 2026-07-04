'use client';

import { useEffect } from 'react';

if (typeof window !== 'undefined' && !(window as any).__fetchPatched) {
  const originalFetch = window.fetch;

  window.fetch = async (...args) => {
    let [resource, config] = args;
    
    const cookies = document.cookie.split(';');
    const tokenCookie = cookies.find(c => c.trim().startsWith('token='));
    const token = tokenCookie ? tokenCookie.trim().substring(6) : null;

    if (token && typeof resource === 'string' && resource.includes('/api/')) {
      config = config || {};
      config.headers = {
        ...config.headers,
        'Authorization': `Bearer ${token}`
      };
    }

    try {
      const response = await originalFetch(resource, config);
      // If we get a 401 Unauthorized, redirect to login
      if (response.status === 401 && window.location.pathname !== '/login') {
        document.cookie = 'token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
        window.location.href = '/login';
      }
      return response;
    } catch (error) {
      throw error;
    }
  };

  (window as any).__fetchPatched = true;
}

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  // We keep the component just to wrap children, no useEffect needed anymore
  return <>{children}</>;
}
