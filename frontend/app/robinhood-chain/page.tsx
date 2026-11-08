import type { Metadata } from "next";
import RobinhoodChainView from "../components/rhc/RobinhoodChainView";

export const metadata: Metadata = {
  title: "Robinhood Chain | Binance Trader Pro",
  description:
    "Robinhood Chain token discovery, safety screening, signals and paper trading. Paper mode only; live trading is disabled.",
};

export default function RobinhoodChainPage() {
  return <RobinhoodChainView />;
}
