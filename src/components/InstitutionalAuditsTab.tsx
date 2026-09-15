import React, { useState, useEffect } from 'react';
import Markdown from 'react-markdown';
import { INSTITUTIONAL_AUDIT_FINDINGS, HISTORICAL_EXPERIMENTS } from '../data/experimentsData';
import { FileText, CheckCircle2, AlertTriangle, ShieldCheck, Tag, Filter, BookOpen, List, Download, Copy, Check, Printer, Layers, FileCheck } from 'lucide-react';
import { apiService } from '../utils/apiService';
import { AuditDocumentMetadata, ExperimentRecord } from '../types';
import { InstitutionalTearSheetGenerator } from './InstitutionalTearSheetGenerator';
import { RegulatoryComplianceHub } from './RegulatoryComplianceHub';

interface InstitutionalAuditsTabProps {
  experiments?: ExperimentRecord[];
}

export const InstitutionalAuditsTab: React.FC<InstitutionalAuditsTabProps> = ({
  experiments = HISTORICAL_EXPERIMENTS,
}) => {
  const [viewMode, setViewMode] = useState<'reader' | 'findings' | 'tear-sheet' | 'regulatory-checklist'>('tear-sheet');
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');
  const [selectedPriority, setSelectedPriority] = useState<string>('ALL');

  // Documents list
  const [documents, setDocuments] = useState<AuditDocumentMetadata[]>([]);
  const [selectedDocFilename, setSelectedDocFilename] = useState<string>('DEEP_AUDIT_2026-09-08.md');
  const [docContent, setDocContent] = useState<string>('');
  const [isLoadingDoc, setIsLoadingDoc] = useState<boolean>(false);
  const [tocHeadings, setTocHeadings] = useState<{ id: string; text: string; level: number }[]>([]);
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    apiService.getAudits().then((list) => {
      setDocuments(list);
    });
  }, []);

  useEffect(() => {
    if (!selectedDocFilename) return;
    setIsLoadingDoc(true);
    apiService.getAuditContent(selectedDocFilename)
      .then((data) => {
        setDocContent(data.content);
        // Extract headings for Table of Contents
        const lines = data.content.split('\n');
        const extracted: { id: string; text: string; level: number }[] = [];
        lines.forEach((line) => {
          const match = line.match(/^(#{1,3})\s+(.+)$/);
          if (match) {
            const level = match[1].length;
            const text = match[2].replace(/[#*_`]/g, '').trim();
            const id = text.toLowerCase().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-');
            extracted.push({ id, text, level });
          }
        });
        setTocHeadings(extracted.slice(0, 18));
      })
      .catch((err) => {
        console.error(err);
        setDocContent('# Failed to load audit document.\nPlease verify that the backend is active.');
      })
      .finally(() => {
        setIsLoadingDoc(false);
      });
  }, [selectedDocFilename]);

  const categories = ['ALL', 'Leakage', 'Accounting', 'Placebo', 'Walk-Forward', 'Data Contract', 'Robustness'];

  const filteredFindings = INSTITUTIONAL_AUDIT_FINDINGS.filter((f) => {
    if (selectedCategory !== 'ALL' && f.category !== selectedCategory) return false;
    if (selectedPriority !== 'ALL' && f.priority !== selectedPriority) return false;
    return true;
  });

  const handleCopyDoc = () => {
    navigator.clipboard.writeText(docContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

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
              Chronological log and full original reports of the institutional audit reviews (Sept 8 - Sept 11, 2026) conducted on this research engine.
              All vulnerabilities—including label unpurging, trial counter resets, corporate action unadjustments, and single-placebo hazards—have been formally remediated and verified.
            </p>
          </div>

          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 font-mono text-xs">
            <CheckCircle2 className="w-4 h-4" />
            <span>7/7 Remediation Audits Verified</span>
          </div>
        </div>
      </div>

      {/* Main Mode Navigation Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900/80 p-2.5 rounded-xl border border-slate-800 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setViewMode('tear-sheet')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg font-semibold transition ${
              viewMode === 'tear-sheet'
                ? 'bg-teal-500 text-slate-950 shadow-md'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Institutional Tear Sheet Generator</span>
          </button>

          <button
            onClick={() => setViewMode('regulatory-checklist')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg font-semibold transition ${
              viewMode === 'regulatory-checklist'
                ? 'bg-teal-500 text-slate-950 shadow-md'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>SEC Rule 15c3-5 &amp; DVC Lineage Hub</span>
          </button>

          <button
            onClick={() => setViewMode('reader')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg font-semibold transition ${
              viewMode === 'reader'
                ? 'bg-teal-500 text-slate-950 shadow-md'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <BookOpen className="w-3.5 h-3.5" />
            <span>Interactive Audit Reader</span>
          </button>

          <button
            onClick={() => setViewMode('findings')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg font-semibold transition ${
              viewMode === 'findings'
                ? 'bg-teal-500 text-slate-950 shadow-md'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <List className="w-3.5 h-3.5" />
            <span>Remediated Vulnerabilities (24 Findings)</span>
          </button>
        </div>

        {viewMode === 'reader' && (
          <button
            onClick={handleCopyDoc}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition font-mono text-xs"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied Full Report' : 'Copy Report MD'}</span>
          </button>
        )}
      </div>

      {/* VIEW MODE: INSTITUTIONAL TEAR SHEET GENERATOR */}
      {viewMode === 'tear-sheet' && (
        <InstitutionalTearSheetGenerator experiments={experiments} />
      )}

      {/* VIEW MODE: REGULATORY COMPLIANCE HUB */}
      {viewMode === 'regulatory-checklist' && (
        <RegulatoryComplianceHub />
      )}

      {/* VIEW MODE 1: FULL MARKDOWN DOCUMENT READER */}
      {viewMode === 'reader' && (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Document Selector & TOC Sidebar */}
          <div className="lg:col-span-1 space-y-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
              <h4 className="text-xs font-mono uppercase text-slate-400 font-semibold tracking-wider">
                Select Audit Document
              </h4>
              <div className="space-y-1.5">
                {documents.map((doc) => (
                  <button
                    key={doc.filename}
                    onClick={() => setSelectedDocFilename(doc.filename)}
                    className={`w-full text-left p-2.5 rounded-lg text-xs transition space-y-1 ${
                      selectedDocFilename === doc.filename
                        ? 'bg-teal-500/20 text-white border border-teal-500/40 font-medium'
                        : 'bg-slate-950/60 text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent'
                    }`}
                  >
                    <div className="font-semibold truncate">{doc.title}</div>
                    <div className="flex items-center justify-between text-[10px] font-mono text-slate-500">
                      <span>{doc.date}</span>
                      <span className={doc.findings?.p1 > 0 ? 'text-amber-400' : 'text-emerald-400'}>
                        {doc.findings?.p1 > 0 ? `${doc.findings.p1} P1s Found` : 'Clean / Passed'}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Table of Contents */}
            {tocHeadings.length > 0 && (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2 sticky top-24">
                <h4 className="text-xs font-mono uppercase text-slate-400 font-semibold tracking-wider">
                  Document Sections
                </h4>
                <div className="space-y-1 max-h-72 overflow-y-auto text-xs font-mono">
                  {tocHeadings.map((h, i) => (
                    <div
                      key={i}
                      className={`text-slate-400 hover:text-teal-300 cursor-pointer truncate py-0.5 ${
                        h.level === 1 ? 'font-bold text-white text-[12px]' : h.level === 2 ? 'pl-2 text-[11px]' : 'pl-4 text-[10px]'
                      }`}
                      onClick={() => {
                        const el = document.getElementById(h.id);
                        if (el) el.scrollIntoView({ behavior: 'smooth' });
                      }}
                    >
                      {h.text}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Markdown Content Display */}
          <div className="lg:col-span-3 bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm overflow-hidden">
            {isLoadingDoc ? (
              <div className="flex items-center justify-center py-24 text-slate-400 font-mono text-xs">
                <span>Loading original audit text from disk...</span>
              </div>
            ) : (
              <div className="markdown-body prose prose-invert max-w-none prose-headings:font-bold prose-headings:text-white prose-p:text-slate-300 prose-p:leading-relaxed prose-code:font-mono prose-code:text-teal-300 prose-code:bg-slate-950 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-pre:bg-slate-950 prose-pre:border prose-pre:border-slate-800 prose-table:text-xs prose-th:text-slate-200 prose-td:text-slate-300">
                <Markdown>{docContent}</Markdown>
              </div>
            )}
          </div>
        </div>
      )}

      {/* VIEW MODE 2: REMEDIATION FINDINGS CARDS */}
      {viewMode === 'findings' && (
        <div className="space-y-4">
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
      )}
    </div>
  );
};
