import React from "react";

export type Status =
  | { type: "idle" }
  | { type: "saving"; message: string }
  | { type: "success" }
  | { type: "error"; message: string };

interface Props {
  status: Status;
}

export default function StatusFeedback({ status }: Props) {
  if (status.type === "idle") return null;

  const styles = {
    saving: "bg-blue-50 text-blue-700",
    success: "bg-green-50 text-green-700",
    error: "bg-red-50 text-red-700",
  };

  return (
    <div className={`mt-3 rounded-md px-3 py-2 text-sm ${styles[status.type]}`}>
      {status.type === "saving" && (
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin" />
          {status.message}
        </div>
      )}
      {status.type === "success" && (
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          Saved to LLM Wiki
        </div>
      )}
      {status.type === "error" && (
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
          {status.message}
        </div>
      )}
    </div>
  );
}
