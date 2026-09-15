import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { LeaderboardTab } from './components/LeaderboardTab';
import { SimulatorTab } from './components/SimulatorTab';
import { PaperTradingTab } from './components/PaperTradingTab';
import { PitAuditTab } from './components/PitAuditTab';
import { InstitutionalAuditsTab } from './components/InstitutionalAuditsTab';
import { ExperimentDetailModal } from './components/ExperimentDetailModal';
import { PreregistrationModal } from './components/PreregistrationModal';
import { HISTORICAL_EXPERIMENTS } from './data/experimentsData';
import { ExperimentRecord, PreregistrationRecord } from './types';
import { apiService } from './utils/apiService';

export function App() {
  const [activeTab, setActiveTab] = useState<string>('leaderboard');
  const [experiments, setExperiments] = useState<ExperimentRecord[]>(HISTORICAL_EXPERIMENTS);
  const [selectedExperiment, setSelectedExperiment] = useState<ExperimentRecord | null>(null);

  // Compute trial counter & highwater mark with live backend sync
  const maxTrialsFromData = Math.max(...experiments.map(e => e.n_trials_global), 63);
  const [globalTrials, setGlobalTrials] = useState<number>(maxTrialsFromData);
  const [highwaterMark, setHighwaterMark] = useState<number>(maxTrialsFromData);

  // Preregistration Gate state
  const [preregistrations, setPreregistrations] = useState<PreregistrationRecord[]>([]);
  const [isPreregModalOpen, setIsPreregModalOpen] = useState<boolean>(false);
  const [selectedPrereg, setSelectedPrereg] = useState<PreregistrationRecord | null>(null);

  const loadPreregistrations = () => {
    apiService.getPreregistrations().then((list) => {
      setPreregistrations(list);
    });
  };

  useEffect(() => {
    // Initial sync with backend API
    apiService.getTrialCounter().then((data) => {
      if (data.currentCount > 0) {
        setGlobalTrials((prev) => Math.max(prev, data.currentCount));
        setHighwaterMark((prev) => Math.max(prev, data.highwaterMark));
      }
    });

    loadPreregistrations();
  }, []);

  const handleRegisterExperiment = (newExp: ExperimentRecord) => {
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

  const handleSelectHypothesisFromPrereg = (prereg: PreregistrationRecord) => {
    setSelectedPrereg(prereg);
    setActiveTab('simulator');
    setIsPreregModalOpen(false);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col selection:bg-teal-500/30 selection:text-teal-200">
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        globalTrials={globalTrials}
        highwaterMark={highwaterMark}
        experimentCount={experiments.length}
        onOpenPreregistration={() => setIsPreregModalOpen(true)}
        activePreregCount={preregistrations.length}
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
            highwaterMark={highwaterMark}
            onRegisterExperiment={handleRegisterExperiment}
            onInspectExperiment={handleSelectExperiment}
            onNavigateToPaperTrading={() => setActiveTab('paper-trading')}
            onOpenPreregistration={() => setIsPreregModalOpen(true)}
            selectedPrereg={selectedPrereg}
            onClearSelectedPrereg={() => setSelectedPrereg(null)}
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
          <InstitutionalAuditsTab experiments={experiments} />
        )}
      </main>

      {/* Preregistration Gate Modal */}
      <PreregistrationModal
        isOpen={isPreregModalOpen}
        onClose={() => setIsPreregModalOpen(false)}
        existingPreregistrations={preregistrations}
        onRefreshPreregistrations={loadPreregistrations}
        onSelectHypothesis={handleSelectHypothesisFromPrereg}
      />

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
