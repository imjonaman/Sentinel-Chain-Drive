import React, { useEffect, useState } from 'react';
import { useTenant } from '../../context/TenantContext';
import { mulechainService } from '../../services/mulechainService';
import { CytoscapeElement } from '../../types/graph';
import { TransactionGraphView } from '../../components/graph/TransactionGraphView';
import { Network, Play, RefreshCw, CheckCircle2 } from 'lucide-react';

export const GraphExplorerPage: React.FC = () => {
  const { activeInstitutionId } = useTenant();
  const [elements, setElements] = useState<CytoscapeElement[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<string | null>(null);

  const fetchGraph = async () => {
    setLoading(true);
    try {
      const graphData = await mulechainService.getGraphElements(activeInstitutionId);
      setElements(graphData);
    } catch (err: unknown) {
      console.warn('Could not load graph elements', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchGraph();
  }, [activeInstitutionId]);

  const handleRunMuleChain = async () => {
    setAnalyzing(true);
    setAnalysisResult(null);
    try {
      const summary = await mulechainService.triggerAnalysis({
        currency: 'USD',
        max_transactions: 1000,
      });
      setAnalysisResult(
        `Analysis complete: ${summary.alerts_generated} alerts generated, ${summary.alerts_deduplicated} deduplicated (${summary.execution_time_ms.toFixed(1)}ms)`
      );
      // Reload graph to reflect newly tagged patterns
      await fetchGraph();
    } catch (err: unknown) {
      setAnalysisResult(err instanceof Error ? `Analysis failed: ${err.message}` : 'Error');
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="space-y-4 h-[calc(100vh-7.5rem)] flex flex-col">
      {/* Top Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shrink-0">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center space-x-2">
            <Network className="w-5 h-5 text-cyan-400" />
            <span>Interactive Cross-Account Transaction Graph Explorer</span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Topology-aware NetworkX graph rendering powered by Cytoscape.js with bounded node expansion.
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={fetchGraph}
            className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
            title="Reload Topology"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>

          <button
            onClick={handleRunMuleChain}
            disabled={analyzing}
            className="px-4 py-2 rounded-xl bg-gradient-to-r from-cyan-600 to-indigo-600 hover:opacity-95 text-white text-xs font-semibold flex items-center space-x-1.5 shadow-lg shadow-cyan-600/20 transition disabled:opacity-50"
          >
            {analyzing ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5 fill-current" />
            )}
            <span>{analyzing ? 'Scanning Topology...' : 'Run MuleChain Detectors'}</span>
          </button>
        </div>
      </div>

      {analysisResult && (
        <div className="p-3 bg-cyan-500/10 border border-cyan-500/20 rounded-xl text-xs text-cyan-300 flex items-center space-x-2 shrink-0">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{analysisResult}</span>
        </div>
      )}

      {/* Full-Height Graph View */}
      <div className="flex-1 min-h-[450px]">
        <TransactionGraphView elements={elements} isLoading={loading} />
      </div>
    </div>
  );
};
