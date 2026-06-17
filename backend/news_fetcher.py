import os
import requests
from datetime import datetime
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database import SessionLocal
from models import NewsArticle

load_dotenv()

POSITIVE_WORDS = {'surge', 'rally', 'bullish', 'rise', 'gain', 'breakout'}
NEGATIVE_WORDS = {'crash', 'drop', 'bearish', 'fall', 'loss', 'dump', 'fear'}

def get_sentiment(text: str) -> str:
    """Analyze text for positive or negative keywords to determine sentiment."""
    if not text:
        return 'Neutral'
        
    text_lower = text.lower()
    # Split text into words (simple tokenization by removing basic punctuation)
    for p in ['.', ',', '!', '?', ':', ';']:
        text_lower = text_lower.replace(p, '')
    words = set(text_lower.split())
    
    pos_count = len(words.intersection(POSITIVE_WORDS))
    neg_count = len(words.intersection(NEGATIVE_WORDS))
    
    if pos_count > neg_count:
        return 'Positive'
    elif neg_count > pos_count:
        return 'Negative'
    else:
        return 'Neutral'

def fetch_and_store_news():
    """Fetches latest BTC news, analyzes sentiment, and stores in the DB."""
    api_key = os.getenv('CRYPTOCOMPARE_API_KEY')
    if not api_key or api_key == 'your_cryptocompare_api_key_here':
        print("Warning: CRYPTOCOMPARE_API_KEY not configured properly.")
        return

    url = "https://min-api.cryptocompare.com/data/v2/news/?lang=EN&categories=BTC"
    headers = {
        "authorization": f"Apikey {api_key}"
    }

    try:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get('Type') != 100: # Success code for this API
            print(f"Error fetching news: {data.get('Message')}")
            return
            
        articles = data.get('Data', [])[:10] # Top 10
        
        db: Session = SessionLocal()
        try:
            stored_count = 0
            for article in articles:
                # API returns unix timestamp
                pub_time = datetime.fromtimestamp(article.get('published_on', 0))
                title = article.get('title', '')
                url_link = article.get('url', '')
                source = article.get('source', '')
                
                # Basic sentiment on headline
                sentiment = get_sentiment(title)
                
                # Avoid duplicates
                existing = db.query(NewsArticle).filter(NewsArticle.url == url_link).first()
                if not existing:
                    new_article = NewsArticle(
                        timestamp=pub_time,
                        title=title,
                        url=url_link,
                        sentiment=sentiment,
                        source=source
                    )
                    db.add(new_article)
                    stored_count += 1
            
            db.commit()
            print(f"Fetched and stored {stored_count} new crypto news articles.")
            
        finally:
            db.close()
            
    except Exception as e:
        print(f"Failed to fetch or store news: {e}")

if __name__ == "__main__":
    fetch_and_store_news()
