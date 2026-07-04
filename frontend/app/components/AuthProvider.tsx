'use client';

import { useEffect } from 'react';
import { useRouter, usePathname } from 'next/navigation';

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Save original fetch
    const originalFetch = window.fetch;

    // Override fetch to automatically attach the token from cookies
    window.fetch = async (...args) => {
      let [resource, config] = args;
      
      const cookies = document.cookie.split(';');
      const tokenCookie = cookies.find(c => c.trim().startsWith('token='));
      const token = tokenCookie ? tokenCookie.split('=')[1] : null;

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
        if (response.status === 401 && pathname !== '/login') {
          document.cookie = 'token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
          window.location.href = '/login';
        }
        return response;
      } catch (error) {
        throw error;
      }
    };

    return () => {
      window.fetch = originalFetch;
    };
  }, [pathname]);

  return <>{children}</>;
}
