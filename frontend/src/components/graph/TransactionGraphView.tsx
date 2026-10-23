import React, { useEffect, useRef, useState } from 'react';
import cytoscape, { Core, EventObject } from 'cytoscape';
import { CytoscapeElement, GraphNodeData, GraphEdgeData } from '../../types/graph';
import {
  Network,
  Filter,
  ZoomIn,
  ZoomOut,
  RefreshCw,
  AlertTriangle,
  ShieldCheck,
  Layers,
  Search,
  Maximize2,
  Compass,
} from 'lucide-react';

interface TransactionGraphViewProps {
  elements: CytoscapeElement[];
  onSelectNode?: (nodeData: GraphNodeData) => void;
  onSelectEdge?: (edgeData: GraphEdgeData) => void;
  isLoading?: boolean;
}

export const TransactionGraphView: React.FC<TransactionGraphViewProps> = ({
  elements,
  onSelectNode,
  onSelectEdge,
  isLoading,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  const [selectedElement, setSelectedElement] = useState<{
    type: 'node' | 'edge';
    data: GraphNodeData | GraphEdgeData;
  } | null>(null);

  const [patternFilter, setPatternFilter] = useState<string>('ALL');
  const [minAmount, setMinAmount] = useState<number>(0);
  const [layoutName, setLayoutName] = useState<string>('cose');
  const [searchQuery, setSearchQuery] = useState<string>('');

  useEffect(() => {
    if (!containerRef.current) return;

    // Filter elements based on UI controls
    const filteredElements = elements.filter((el) => {
      if (el.group === 'edges') {
        const edge = el.data as GraphEdgeData;
        if (patternFilter !== 'ALL' && edge.pattern_type !== patternFilter) {
          return false;
        }
        if (minAmount > 0 && parseFloat(edge.amount || '0') < minAmount) {
          return false;
        }
      }
      return true;
    });

    // Initialize Cytoscape
    const cy = cytoscape({
      container: containerRef.current,
      elements: filteredElements as cytoscape.ElementDefinition[],
      boxSelectionEnabled: false,
      autounselectify: false,
      style: [
        // Account Node Styling
        {
          selector: 'node',
          style: {
            'label': 'data(label)',
            'color': '#cbd5e1',
            'font-size': '11px',
            'font-family': 'Inter, sans-serif',
            'text-valign': 'bottom',
            'text-margin-y': 5,
            'background-color': '#0f172a',
            'border-width': 2,
            'border-color': '#475569',
            'width': 38,
            'height': 38,
            'transition-property': 'background-color, border-color, width, height',
            'transition-duration': 0.2,
          },
        },
        // Risk Status Node Highlighting
        {
          selector: 'node[risk_status = "NORMAL"], node[riskStatus = "NORMAL"]',
          style: {
            'background-color': '#064e3b',
            'border-color': '#10b981',
            'border-width': 2.5,
          },
        },
        {
          selector: 'node[risk_status = "SUSPICIOUS"], node[riskStatus = "SUSPICIOUS"]',
          style: {
            'background-color': '#78350f',
            'border-color': '#f59e0b',
            'border-width': 3,
          },
        },
        {
          selector: 'node[risk_status = "HIGH_RISK"], node[riskStatus = "HIGH_RISK"]',
          style: {
            'background-color': '#831843',
            'border-color': '#f43f5e',
            'border-width': 3.5,
            'width': 42,
            'height': 42,
          },
        },
        {
          selector: 'node[risk_status = "CRITICAL"], node[riskStatus = "CRITICAL"]',
          style: {
            'background-color': '#7f1d1d',
            'border-color': '#ef4444',
            'border-width': 4,
            'width': 46,
            'height': 46,
          },
        },
        // Transaction Edge Styling
        {
          selector: 'edge',
          style: {
            'width': 2,
            'line-color': '#334155',
            'target-arrow-color': '#475569',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'opacity': 0.7,
            'arrow-scale': 0.8,
          },
        },
        // Pattern Highlights
        {
          selector: 'edge[pattern_type = "FAN_IN"]',
          style: {
            'line-color': '#38bdf8',
            'target-arrow-color': '#38bdf8',
            'width': 3.5,
            'opacity': 0.95,
          },
        },
        {
          selector: 'edge[pattern_type = "FAN_OUT"]',
          style: {
            'line-color': '#a855f7',
            'target-arrow-color': '#a855f7',
            'width': 3.5,
            'opacity': 0.95,
          },
        },
        {
          selector: 'edge[pattern_type = "PASS_THROUGH"]',
          style: {
            'line-color': '#f59e0b',
            'target-arrow-color': '#f59e0b',
            'width': 4,
            'opacity': 1,
            'line-style': 'dashed',
          },
        },
        {
          selector: 'edge[pattern_type = "CYCLE"]',
          style: {
            'line-color': '#ef4444',
            'target-arrow-color': '#ef4444',
            'width': 4,
            'opacity': 1,
          },
        },
        // Selected highlights
        {
          selector: 'node:selected',
          style: {
            'border-color': '#6366f1',
            'border-width': 4,
            'width': 48,
            'height': 48,
          },
        },
        {
          selector: 'edge:selected',
          style: {
            'width': 4,
            'line-color': '#6366f1',
            'target-arrow-color': '#6366f1',
            'opacity': 1,
          },
        },
      ],
      layout: {
        name: layoutName,
        animate: false,
        nodeDimensionsIncludeLabels: true,
        idealEdgeLength: () => 100,
        nodeOverlap: 20,
      } as any,
    });

    cy.on('tap', 'node', (evt: EventObject) => {
      const node = evt.target;
      const data = node.data() as GraphNodeData;
      setSelectedElement({ type: 'node', data });
      if (onSelectNode) onSelectNode(data);
    });

    cy.on('tap', 'edge', (evt: EventObject) => {
      const edge = evt.target;
      const data = edge.data() as GraphEdgeData;
      setSelectedElement({ type: 'edge', data });
      if (onSelectEdge) onSelectEdge(data);
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
    };
  }, [elements, patternFilter, minAmount, layoutName, onSelectNode, onSelectEdge]);

  const handleZoomIn = () => cyRef.current?.zoom(cyRef.current.zoom() * 1.25);
  const handleZoomOut = () => cyRef.current?.zoom(cyRef.current.zoom() * 0.8);
  const handleFit = () => cyRef.current?.fit();

  const handleSearchNode = (e: React.FormEvent) => {
    e.preventDefault();
    if (!cyRef.current || !searchQuery) return;
    const query = searchQuery.trim().toLowerCase();
    const node = cyRef.current.nodes().filter((n) => {
      const d = n.data() as GraphNodeData;
      return d.id.toLowerCase().includes(query) || d.label.toLowerCase().includes(query);
    }).first();

    if (node && node.length > 0) {
      cyRef.current.animate({
        center: { eles: node },
        zoom: 1.8,
        duration: 500,
      });
      node.select();
      setSelectedElement({ type: 'node', data: node.data() as GraphNodeData });
    }
  };

  const nodeCount = elements.filter((e) => e.group === 'nodes').length;
  const edgeCount = elements.filter((e) => e.group === 'edges').length;

  return (
    <div className="flex flex-col h-full rounded-2xl border border-slate-800 bg-[#080D1A] overflow-hidden shadow-2xl">
      {/* Top Filter and Controls Bar */}
      <div className="p-3.5 border-b border-slate-800/90 bg-slate-900/80 backdrop-blur-md flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-3">
          <div className="p-2 rounded-xl bg-gradient-to-tr from-cyan-500/20 to-indigo-500/20 text-cyan-400 border border-cyan-500/30">
            <Network className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h2 className="text-sm font-bold text-white tracking-wide">MuleChain Topological Explorer</h2>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 font-mono text-cyan-300 border border-slate-700">
                {nodeCount} Nodes · {edgeCount} Flows
              </span>
            </div>
            <p className="text-[11px] text-slate-400">Interactive Cytoscape Directed Multigraph Engine</p>
          </div>
        </div>

        {/* Filter and Control Tools */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Quick Node Search */}
          <form onSubmit={handleSearchNode} className="relative">
            <input
              type="text"
              placeholder="Find Account / UUID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-44 pl-7 pr-2.5 py-1.5 rounded-xl bg-slate-800/90 border border-slate-700 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
            />
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5 pointer-events-none" />
          </form>

          {/* Pattern Filter */}
          <div className="flex items-center space-x-1.5 text-xs bg-slate-800/90 px-2.5 py-1.5 rounded-xl border border-slate-700">
            <Filter className="w-3.5 h-3.5 text-slate-400" />
            <select
              aria-label="Filter Topology Pattern"
              value={patternFilter}
              onChange={(e) => setPatternFilter(e.target.value)}
              className="bg-transparent text-slate-200 focus:outline-none text-xs"
            >
              <option value="ALL">All Patterns</option>
              <option value="FAN_IN">Fan-In Smurfing</option>
              <option value="FAN_OUT">Fan-Out Dispersal</option>
              <option value="PASS_THROUGH">Rapid Pass-Through</option>
              <option value="CYCLE">Circular Layering</option>
            </select>
          </div>

          {/* Layout Selector */}
          <div className="flex items-center space-x-1.5 text-xs bg-slate-800/90 px-2.5 py-1.5 rounded-xl border border-slate-700">
            <Compass className="w-3.5 h-3.5 text-indigo-400" />
            <select
              aria-label="Graph Layout"
              value={layoutName}
              onChange={(e) => setLayoutName(e.target.value)}
              className="bg-transparent text-slate-200 focus:outline-none text-xs"
            >
              <option value="cose">CoSE Force-Directed</option>
              <option value="concentric">Concentric Hierarchy</option>
              <option value="circle">Circular Topology</option>
              <option value="breadthfirst">Breadth-First Trees</option>
            </select>
          </div>

          {/* Amount Slider */}
          <div className="hidden sm:flex items-center space-x-2 text-xs bg-slate-800/90 px-2.5 py-1.5 rounded-xl border border-slate-700">
            <span className="text-slate-400">Min:</span>
            <input
              type="range"
              min="0"
              max="10000"
              step="500"
              value={minAmount}
              onChange={(e) => setMinAmount(Number(e.target.value))}
              className="w-16 accent-indigo-500 cursor-pointer"
            />
            <span className="font-mono text-cyan-300 font-bold">${minAmount}</span>
          </div>

          {/* Zoom & Fit Actions */}
          <div className="flex items-center space-x-1 border-l border-slate-700 pl-2">
            <button
              onClick={handleZoomIn}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
              title="Zoom In"
            >
              <ZoomIn className="w-4 h-4" />
            </button>
            <button
              onClick={handleZoomOut}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
              title="Zoom Out"
            >
              <ZoomOut className="w-4 h-4" />
            </button>
            <button
              onClick={handleFit}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
              title="Reset View"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Main Canvas and Inspector Split */}
      <div className="flex-1 relative min-h-[520px]">
        {/* Cytoscape DOM Mount */}
        <div ref={containerRef} className="absolute inset-0 w-full h-full" />

        {isLoading && (
          <div className="absolute inset-0 bg-[#070A12]/80 backdrop-blur-md flex items-center justify-center z-20">
            <div className="flex items-center space-x-3 text-cyan-400 p-4 rounded-2xl bg-slate-900 border border-slate-800 shadow-2xl">
              <RefreshCw className="w-5 h-5 animate-spin" />
              <span className="text-xs font-semibold font-mono">Synthesizing Topological Network...</span>
            </div>
          </div>
        )}

        {/* Legend Overlay */}
        <div className="absolute bottom-4 left-4 bg-slate-900/90 backdrop-blur-md border border-slate-800 p-3.5 rounded-2xl text-[11px] space-y-1.5 z-10 shadow-2xl pointer-events-none">
          <div className="font-bold text-slate-300 uppercase tracking-wider text-[10px] mb-1 flex items-center space-x-1.5">
            <Layers className="w-3.5 h-3.5 text-cyan-400" />
            <span>Topology Legend</span>
          </div>
          <div className="flex items-center space-x-2 text-emerald-400">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-sm shadow-emerald-500/50"></span>
            <span>Clean Account</span>
          </div>
          <div className="flex items-center space-x-2 text-amber-400">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500 shadow-sm shadow-amber-500/50"></span>
            <span>Suspicious Ingress / Velocity</span>
          </div>
          <div className="flex items-center space-x-2 text-rose-400">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500 shadow-sm shadow-rose-500/50"></span>
            <span>High Risk / Mule Node</span>
          </div>
          <div className="flex items-center space-x-2 text-red-500">
            <span className="w-2.5 h-2.5 rounded-full bg-red-600 shadow-sm shadow-red-500/50"></span>
            <span>Critical Layering Cycle</span>
          </div>
        </div>

        {/* Node/Edge Detail Inspector Card */}
        {selectedElement && (
          <div className="absolute top-4 right-4 w-80 bg-slate-950/95 backdrop-blur-xl border border-slate-800 p-4 rounded-2xl text-xs shadow-2xl z-20 space-y-3 animate-fadeIn">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
              <div className="font-semibold text-white flex items-center space-x-1.5">
                {selectedElement.type === 'node' ? (
                  <>
                    <ShieldCheck className="w-4 h-4 text-cyan-400" />
                    <span>Inspected Account Node</span>
                  </>
                ) : (
                  <>
                    <AlertTriangle className="w-4 h-4 text-amber-400" />
                    <span>Inspected Transaction Flow</span>
                  </>
                )}
              </div>
              <button
                onClick={() => setSelectedElement(null)}
                className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800"
              >
                ✕
              </button>
            </div>

            {selectedElement.type === 'node' ? (
              <div className="space-y-2 font-mono text-[11px]">
                <div>
                  <span className="text-slate-500 block text-[10px]">ACCOUNT UUID</span>
                  <span className="text-slate-200 select-all block truncate font-semibold">
                    {(selectedElement.data as GraphNodeData).id}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 pt-1 border-t border-slate-800/80">
                  <div>
                    <span className="text-slate-500 block text-[10px]">TYPE</span>
                    <span className="text-indigo-300 font-bold">{(selectedElement.data as GraphNodeData).account_type || 'CHECKING'}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px]">CURRENCY</span>
                    <span className="text-white font-bold">{(selectedElement.data as GraphNodeData).currency}</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 pt-1 border-t border-slate-800/80">
                  <div>
                    <span className="text-slate-500 block text-[10px]">RISK STATUS</span>
                    <span
                      className={`font-bold ${
                        (selectedElement.data as GraphNodeData).risk_status === 'CRITICAL'
                          ? 'text-red-400'
                          : (selectedElement.data as GraphNodeData).risk_status === 'HIGH_RISK'
                          ? 'text-rose-400'
                          : (selectedElement.data as GraphNodeData).risk_status === 'SUSPICIOUS'
                          ? 'text-amber-400'
                          : 'text-emerald-400'
                      }`}
                    >
                      {(selectedElement.data as GraphNodeData).risk_status}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px]">ALERTS LINKED</span>
                    <span className="text-rose-400 font-bold">{(selectedElement.data as GraphNodeData).alert_count}</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-2 font-mono text-[11px]">
                <div>
                  <span className="text-slate-500 block text-[10px]">TRANSACTION ID</span>
                  <span className="text-slate-200 select-all block truncate font-semibold">
                    {(selectedElement.data as GraphEdgeData).id}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 pt-1 border-t border-slate-800/80">
                  <div>
                    <span className="text-slate-500 block text-[10px]">AMOUNT</span>
                    <span className="text-emerald-400 font-extrabold">
                      ${parseFloat((selectedElement.data as GraphEdgeData).amount).toFixed(2)} {(selectedElement.data as GraphEdgeData).currency}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px]">PATTERN</span>
                    <span className="text-cyan-300 font-bold">{(selectedElement.data as GraphEdgeData).pattern_type || 'DIRECT_TRANSFER'}</span>
                  </div>
                </div>
                <div className="pt-1 border-t border-slate-800/80">
                  <span className="text-slate-500 block text-[10px]">SETTLEMENT STATE</span>
                  <span className="text-indigo-300 font-medium">{(selectedElement.data as GraphEdgeData).status}</span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
