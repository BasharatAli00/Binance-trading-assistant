// WebSocket probe using Node's built-in WebSocket (Node 22+). Read-only subscription to newHeads.
const urls = ["wss://rpc.mainnet.chain.robinhood.com", "wss://rpc.mainnet.chain.robinhood.com/ws"];
for (const url of urls) {
  await new Promise((resolve) => {
    const t = setTimeout(() => { console.log(url, "TIMEOUT"); try { ws.close(); } catch {} resolve(); }, 10000);
    let ws;
    try { ws = new WebSocket(url); } catch (e) { console.log(url, "ERR", e.message); clearTimeout(t); return resolve(); }
    let n = 0;
    ws.onopen = () => ws.send(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_subscribe", params: ["newHeads"] }));
    ws.onmessage = (m) => {
      n++;
      console.log(url, "MSG", String(m.data).slice(0, 160));
      if (n >= 3) { clearTimeout(t); ws.close(); resolve(); }
    };
    ws.onerror = (e) => { console.log(url, "ERR", e.message || e.type); clearTimeout(t); resolve(); };
  });
}
