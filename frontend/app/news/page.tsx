'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

type NewsArticle = {
  id: string;
  timestamp: string;
  title: string;
  url: string;
  sentiment: string;
  source: string;
};

export default function NewsPage() {
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchNews = async () => {
      try {
        const res = await fetch(`${API_URL}/api/news`);
        const data = await res.json();
        if (Array.isArray(data)) {
          setNews(data);
        } else {
          console.error("Expected array from /api/news but got:", data);
          setNews([]);
        }
      } catch (err) {
        console.error("Error fetching news", err);
      } finally {
        setLoading(false);
      }
    };
    fetchNews();
    
    const interval = setInterval(fetchNews, 300000);
    return () => clearInterval(interval);
  }, []);

  const getSentimentBadge = (sentiment: string) => {
    switch (sentiment) {
      case 'Positive':
        return <span className="text-xs px-2 py-0.5 rounded bg-green-900 text-green-300 font-bold">Positive</span>;
      case 'Negative':
        return <span className="text-xs px-2 py-0.5 rounded bg-red-900 text-red-300 font-bold">Negative</span>;
      default:
        return <span className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-400 font-bold">Neutral</span>;
    }
  };

  return (
    <div className="flex flex-col gap-6 h-full">
      <header className="shrink-0 flex justify-between items-center pb-3 border-b border-[#2b3139]">
        <h2 className="text-xl font-bold text-white tracking-wide">Crypto News</h2>
      </header>

      <div className="bg-[#111111] border border-[#222222] rounded-lg p-6 shadow-lg flex-1 overflow-y-auto custom-scrollbar">
        {loading ? (
          <div className="text-gray-500 text-sm flex items-center justify-center h-full">Loading news...</div>
        ) : news.length === 0 ? (
          <div className="text-gray-500 text-sm flex items-center justify-center h-full">No news available</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {news.map((item) => (
              <a
                key={item.id}
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex flex-col gap-3 group cursor-pointer bg-[#1a1a1a] p-4 rounded-lg border border-[#2b3139] hover:border-[#f0b90b] transition-colors"
              >
                <div className="text-gray-200 text-base font-sans line-clamp-3 leading-snug group-hover:text-white">
                  {item.title}
                </div>
                <div className="mt-auto pt-4 flex items-center justify-between font-mono border-t border-[#2b3139]">
                  {getSentimentBadge(item.sentiment)}
                  <span className="text-xs text-gray-500">
                    {new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
