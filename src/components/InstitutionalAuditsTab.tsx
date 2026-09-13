import React, { useState } from 'react';
import { INSTITUTIONAL_AUDIT_FINDINGS } from '../data/experimentsData';
import { FileText, CheckCircle2, AlertTriangle, ShieldCheck, Tag, Filter } from 'lucide-react';

export const InstitutionalAuditsTab: React.FC = () => {
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');
  const [selectedPriority, setSelectedPriority] = useState<string>('ALL');

  const categories = ['ALL', 'Leakage', 'Accounting', 'Placebo', 'Walk-Forward', 'Data Contract', 'Robustness'];

  const filteredFindings = INSTITUTIONAL_AUDIT_FINDINGS.filter((f) => {
    if (selectedCategory !== 'ALL' && f.category !== selectedCategory) return false;
    if (selectedPriority !== 'ALL' && f.priority !== selectedPriority) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Introduction */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <FileText className="w-5 h-5 text-teal-400" />
              <span>Institutional Audit Archive & Audit Trails</span>
            </h3>
            <p className="text-xs sm:text-sm text-slate-400 mt-1 max-w-3xl">
              Chronological log of the institutional audit reviews (Sept 8 - Sept 11, 2026) conducted on this research engine.
              All vulnerabilities—including label unpurging, trial counter resets, corporate action unadjustments, and single-placebo hazards—have been formally remediated and verified.
            </p>
          </div>

          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 font-mono text-xs">
            <CheckCircle2 className="w-4 h-4" />
            <span>7/7 Remediation Audits Verified</span>
          </div>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900/60 p-3 rounded-xl border border-slate-800 text-xs">
        <div className="flex items-center gap-2 overflow-x-auto">
          <span className="text-slate-500 font-mono uppercase text-[10px]">Category:</span>
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-2.5 py-1 rounded-md font-medium transition whitespace-nowrap ${
                selectedCategory === cat
                  ? 'bg-teal-500/20 text-teal-300 border border-teal-500/30'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-slate-500 font-mono uppercase text-[10px]">Priority:</span>
          {['ALL', 'P1', 'P2'].map((p) => (
            <button
              key={p}
              onClick={() => setSelectedPriority(p)}
              className={`px-2 py-0.5 rounded font-mono font-bold transition ${
                selectedPriority === p
                  ? 'bg-slate-800 text-white border border-slate-700'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Findings List */}
      <div className="space-y-4">
        {filteredFindings.map((finding) => (
          <div
            key={finding.id}
            className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3"
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2.5">
                <span className="font-mono text-xs text-slate-500">{finding.id}</span>
                <span className={`px-2 py-0.5 rounded font-mono text-[10px] font-bold ${
                  finding.priority === 'P1'
                    ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                    : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                }`}>
                  {finding.priority}
                </span>
                <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono text-[10px] border border-slate-700">
                  {finding.category}
                </span>
                <h4 className="font-bold text-white text-sm">{finding.title}</h4>
              </div>

              <div className="flex items-center gap-2 font-mono text-xs">
                <span className="text-slate-500">{finding.audit_date}</span>
                <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-semibold text-[10px] flex items-center gap-1 border border-emerald-500/30">
                  <CheckCircle2 className="w-3 h-3" />
                  VERIFIED FIXED
                </span>
              </div>
            </div>

            <div className="text-xs text-slate-300 leading-relaxed">
              {finding.description}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs pt-1">
              <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/80">
                <div className="text-rose-400 font-semibold mb-1 flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>Theoretical Failure Impact</span>
                </div>
                <p className="text-slate-400 leading-relaxed">{finding.impact}</p>
              </div>

              <div className="p-3 bg-slate-950 rounded-lg border border-teal-900/30 bg-teal-950/10">
                <div className="text-teal-300 font-semibold mb-1 flex items-center gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5" />
                  <span>Technical Remediation Implemented</span>
                </div>
                <p className="text-slate-300 font-mono text-[11px] leading-relaxed">{finding.remediation}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
