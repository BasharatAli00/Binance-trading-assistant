import threading
import time
from datetime import datetime

import copytrade_config as cfg
import copytrade_signal as signal

# Thread-safe in-memory cache for event deduplication
# Key: signature_wallet_mint_side
_dedup_cache = {}
_cache_lock = threading.Lock()

# Heartbeats
_last_event_time = {
    "helius": 0.0,
    "quicknode": 0.0
}

def process_event(source: str, event: dict):
    """
    Process an incoming parsed event from a webhook source.
    Dedups across sources, updates heartbeats, and forwards to the signal layer.
    """
    now = time.time()
    _last_event_time[source] = now
    
    if source == "quicknode" and cfg.QUICKNODE_SHADOW_ONLY:
        # Stage 1: log and discard
        print(f"[copytrade] [SHADOW] QuickNode event parsed: {event.get('signature', '')[:8]}")
        return 0

    sig = event.get("signature")
    if not sig:
        return 0
        
    key = f"{sig}_{event.get('wallet')}_{event.get('mint')}_{event.get('side')}"
    
    with _cache_lock:
        # Clean up old entries periodically
        if len(_dedup_cache) > 1000:
            cutoff = now - cfg.DEDUP_CACHE_TTL_SECONDS
            keys_to_delete = [k for k, v in _dedup_cache.items() if v < cutoff]
            for k in keys_to_delete:
                del _dedup_cache[k]

        if key in _dedup_cache:
            # Duplicate
            return 0
            
        _dedup_cache[key] = now
    
    # Not a duplicate, forward it
    event["source"] = source
    return signal.record_events([event])

def check_heartbeats():
    """Log warnings if a feed goes silent."""
    now = time.time()
    threshold = cfg.SOURCE_SILENT_THRESHOLD_SECONDS
    
    if _last_event_time["helius"] > 0 and now - _last_event_time["helius"] > threshold:
        print(f"[copytrade] WARNING: Helius feed silent for >{threshold}s")
        
    if cfg.ENABLE_QUICKNODE_FEED:
        if _last_event_time["quicknode"] > 0 and now - _last_event_time["quicknode"] > threshold:
            print(f"[copytrade] WARNING: QuickNode feed silent for >{threshold}s")
