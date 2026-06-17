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

export default function NewsWidget() {
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
    
    // News updates hourly in the backend, but we can poll every 5 mins to be fresh
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

  if (loading) {
    return (
      <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg flex flex-col min-h-[200px]">
        <div className="text-gray-400 text-sm font-bold font-sans mb-3">LATEST NEWS</div>
        <div className="text-gray-500 text-sm flex-1 flex items-center justify-center">Loading news...</div>
      </div>
    );
  }

  if (news.length === 0) {
    return (
      <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg flex flex-col min-h-[200px]">
        <div className="text-gray-400 text-sm font-bold font-sans mb-3">LATEST NEWS</div>
        <div className="text-gray-500 text-sm flex-1 flex items-center justify-center">No news available</div>
      </div>
    );
  }

  return (
    <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 shadow-lg hover:border-gray-500 transition-colors flex flex-col">
      <div className="flex justify-between items-center mb-4">
        <span className="text-gray-400 text-sm font-bold font-sans">LATEST NEWS</span>
        <span className="text-xs text-gray-500 font-mono">Top 3 Articles</span>
      </div>

      <div className="flex flex-col gap-4">
        {news.map((item) => (
          <a
            key={item.id}
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex flex-col gap-1.5 group cursor-pointer"
          >
            <div className="text-gray-200 text-sm font-sans line-clamp-2 leading-snug group-hover:text-white group-hover:underline">
              {item.title}
            </div>
            <div className="flex items-center gap-2 font-mono">
              {getSentimentBadge(item.sentiment)}
              <span className="text-[10px] text-gray-500">
                {new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
