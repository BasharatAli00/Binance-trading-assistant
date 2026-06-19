import PortfolioView from "../components/PortfolioView";

export default function PortfolioPage() {
  return (
    <div className="flex flex-col gap-6">
      <header className="shrink-0 flex justify-between items-center pb-3 border-b border-[var(--color-border)]">
        <h2 className="text-2xl font-bold text-white tracking-wide">My Portfolio</h2>
      </header>
      <PortfolioView symbol="BTCUSDT" />
    </div>
  );
}
