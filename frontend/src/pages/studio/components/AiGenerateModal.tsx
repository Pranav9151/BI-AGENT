/**
 * Smart BI Agent — AiGenerateModal
 * Prompt dialog for auto-generating dashboards from natural language.
 */

import { useState } from "react";
import { Wand2, X } from "lucide-react";
import { Button } from "@/components/ui";

interface AiGenerateModalProps {
  onGenerate: (prompt: string) => void;
  onClose: () => void;
}

const SUGGESTIONS = [
  "Sales overview",
  "Customer analytics",
  "Revenue trends",
  "Product performance",
];

export function AiGenerateModal({ onGenerate, onClose }: AiGenerateModalProps) {
  const [prompt, setPrompt] = useState("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative w-full max-w-md glass-strong rounded-2xl shadow-2xl animate-scale-in">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-700/40">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Wand2 className="h-4 w-4 text-violet-400" />
            AI Dashboard Builder
          </h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4">
          <p className="text-xs text-slate-400">
            Describe the dashboard you want. AI will create multiple visuals
            automatically.
          </p>
          <input
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && prompt.trim()) onGenerate(prompt.trim());
            }}
            placeholder="e.g. Sales performance by region with monthly trends"
            className="w-full h-10 rounded-lg border border-slate-700/40 bg-slate-800/30 text-slate-200 text-sm px-3 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
            autoFocus
          />
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => setPrompt(s)}
                className="text-[10px] px-2.5 py-1 rounded-lg border border-slate-700/30 text-slate-500 hover:text-violet-300 hover:border-violet-500/20 transition-all duration-200"
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 p-5 border-t border-slate-700/40">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => prompt.trim() && onGenerate(prompt.trim())}
            disabled={!prompt.trim()}
            icon={<Wand2 className="h-3.5 w-3.5" />}
          >
            Generate
          </Button>
        </div>
      </div>
    </div>
  );
}
