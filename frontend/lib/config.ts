const isLocal = typeof window !== 'undefined' 
  ? window.location.hostname === 'localhost' 
  : process.env.NODE_ENV === 'development';

const rawApiUrl = isLocal 
  ? "http://localhost:8000" 
  : (process.env.NEXT_PUBLIC_API_URL || "https://bushutrading-cccnfhede7gyhdcp.centralindia-01.azurewebsites.net");

// Strip any trailing slash to prevent double-slash in API routes (e.g. //api/login)
const API_URL = rawApiUrl.replace(/\/+$/, "");

export default API_URL;
