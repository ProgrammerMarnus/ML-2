import React, { useState } from 'react';
import { Header } from './components/Header';
import { LeaderboardTab } from './components/LeaderboardTab';
import { SimulatorTab } from './components/SimulatorTab';
import { PaperTradingTab } from './components/PaperTradingTab';
import { PitAuditTab } from './components/PitAuditTab';
import { InstitutionalAuditsTab } from './components/InstitutionalAuditsTab';
import { ExperimentDetailModal } from './components/ExperimentDetailModal';
import { HISTORICAL_EXPERIMENTS } from './data/experimentsData';
import { ExperimentRecord } from './types';

export function App() {
  const [activeTab, setActiveTab] = useState<string>('leaderboard');
  const [experiments, setExperiments] = useState<ExperimentRecord[]>(HISTORICAL_EXPERIMENTS);
  const [selectedExperiment, setSelectedExperiment] = useState<ExperimentRecord | null>(null);

  // Compute trial counter & highwater mark
  const maxTrialsFromData = Math.max(...experiments.map(e => e.n_trials_global), 63);
  const [globalTrials, setGlobalTrials] = useState<number>(maxTrialsFromData);
  const [highwaterMark, setHighwaterMark] = useState<number>(maxTrialsFromData);

  const handleRegisterExperiment = (newExp: ExperimentRecord) => {
    // Add to top of experiments
    setExperiments(prev => [newExp, ...prev]);
    const updatedTrials = Math.max(globalTrials + newExp.trials_this_experiment, newExp.n_trials_global);
    setGlobalTrials(updatedTrials);
    if (updatedTrials > highwaterMark) {
      setHighwaterMark(updatedTrials);
    }
  };

  const handleSelectExperiment = (exp: ExperimentRecord) => {
    setSelectedExperiment(exp);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col selection:bg-teal-500/30 selection:text-teal-200">
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        globalTrials={globalTrials}
        highwaterMark={highwaterMark}
        experimentCount={experiments.length}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {activeTab === 'leaderboard' && (
          <LeaderboardTab
            experiments={experiments}
            onSelectExperiment={handleSelectExperiment}
          />
        )}

        {activeTab === 'simulator' && (
          <SimulatorTab
            globalTrials={globalTrials}
            onRegisterExperiment={handleRegisterExperiment}
            onInspectExperiment={handleSelectExperiment}
            onNavigateToPaperTrading={() => setActiveTab('paper-trading')}
          />
        )}

        {activeTab === 'paper-trading' && (
          <PaperTradingTab
            experiments={experiments}
          />
        )}

        {activeTab === 'pit-audit' && (
          <PitAuditTab
            globalTrials={globalTrials}
            highwaterMark={highwaterMark}
          />
        )}

        {activeTab === 'institutional-audits' && (
          <InstitutionalAuditsTab />
        )}
      </main>

      {/* Experiment Detail Inspector Modal */}
      {selectedExperiment && (
        <ExperimentDetailModal
          experiment={selectedExperiment}
          onClose={() => setSelectedExperiment(null)}
        />
      )}

      {/* Footer */}
      <footer className="border-t border-slate-900 bg-slate-950 py-4 text-center text-xs text-slate-500 font-mono">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-2">
          <span>Institutional Quant Research Engine • Built on ProgrammerMarnus/ML-2</span>
          <span>Point-in-Time Invariant • LockedTestProtocol • 11 Promotion Gates</span>
        </div>
      </footer>
    </div>
  );
}

export default App;
