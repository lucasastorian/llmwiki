import React, { useEffect, useState, useRef } from "react";
import type { KnowledgeBase } from "@/lib/api";
import { fetchKnowledgeBases, createKnowledgeBase } from "@/lib/api";

interface Props {
  apiUrl: string;
  accessToken: string | null;
  value: string | null;
  onChange: (id: string) => void;
}

export default function KBPicker({ apiUrl, accessToken, value, onChange }: Props) {
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadKBs();
  }, [apiUrl, accessToken]);

  useEffect(() => {
    if (creating) inputRef.current?.focus();
  }, [creating]);

  async function loadKBs() {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchKnowledgeBases(apiUrl, accessToken);
      setKbs(list);
      if (!value && list.length > 0) {
        onChange(list[0].id);
      }
    } catch {
      setError("Failed to load knowledge bases");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate() {
    const name = newName.trim();
    if (!name) return;
    try {
      const kb = await createKnowledgeBase(apiUrl, accessToken, name);
      setKbs((prev) => [kb, ...prev]);
      onChange(kb.id);
      setCreating(false);
      setNewName("");
    } catch {
      setError("Failed to create knowledge base");
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") { e.preventDefault(); handleCreate(); }
    if (e.key === "Escape") { setCreating(false); setNewName(""); }
  }

  if (loading) {
    return <div className="text-xs text-gray-400 py-1">Loading knowledge bases...</div>;
  }

  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-gray-600">Knowledge Base</label>

      {!creating ? (
        <div className="flex gap-2">
          <select
            value={value ?? ""}
            onChange={(e) => { if (e.target.value) onChange(e.target.value); }}
            className="flex-1 rounded-md border border-gray-300 bg-white px-3 py-1.5
                       text-sm text-gray-900 shadow-sm focus:border-gray-900
                       focus:ring-1 focus:ring-gray-900 outline-none"
          >
            {kbs.length === 0 && (
              <option value="" disabled>No knowledge bases — create one</option>
            )}
            {kbs.map((kb) => (
              <option key={kb.id} value={kb.id}>{kb.name}</option>
            ))}
          </select>
          <button
            onClick={() => setCreating(true)}
            className="px-2 py-1.5 text-xs font-medium text-gray-700 hover:text-gray-900
                       border border-gray-300 rounded-md hover:bg-gray-50 transition-colors
                       whitespace-nowrap"
          >
            + New
          </button>
        </div>
      ) : (
        <div className="flex gap-2">
          <input
            ref={inputRef}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Knowledge base name"
            className="flex-1 rounded-md border border-gray-300 px-3 py-1.5
                       text-sm text-gray-900 shadow-sm focus:border-gray-900
                       focus:ring-1 focus:ring-gray-900 outline-none"
          />
          <button
            onClick={handleCreate}
            disabled={!newName.trim()}
            className="px-3 py-1.5 text-xs font-medium text-white bg-gray-900 rounded-md
                       hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed
                       transition-colors"
          >
            Add
          </button>
          <button
            onClick={() => { setCreating(false); setNewName(""); }}
            className="px-2 py-1.5 text-xs text-gray-500 hover:text-gray-700"
          >
            Cancel
          </button>
        </div>
      )}

      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  );
}
