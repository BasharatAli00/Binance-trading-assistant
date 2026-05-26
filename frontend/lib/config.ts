const isLocal = typeof window !== 'undefined' 
  ? window.location.hostname === 'localhost' 
  : process.env.NODE_ENV === 'development';

const API_URL = isLocal 
  ? "http://localhost:8000" 
  : (process.env.NEXT_PUBLIC_API_URL || "https://binance-trading-bot-etdpfbdhdrh6ezgt.centralindia-01.azurewebsites.net");

export default API_URL;
