import { useState } from "react";
import { Send } from "lucide-react";

interface CorrectionPanelProps {
  busy: string | null;
  onCorrection: (message: string) => Promise<void>;
}

export function CorrectionPanel({ busy, onCorrection }: CorrectionPanelProps) {
  const [message, setMessage] = useState("");

  async function submit() {
    if (!message.trim() || busy) return;
    await onCorrection(message.trim());
    setMessage("");
  }

  return (
    <section className="panel">
      <h2>Correction</h2>
      <textarea
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={(event) => {
          if (event.ctrlKey && event.key === "Enter") {
            void submit();
          }
        }}
        placeholder="Message to task / correction request"
        rows={5}
      />
      <button type="button" disabled={!message.trim() || busy === "correction"} onClick={() => void submit()}>
        <Send size={16} />
        {busy === "correction" ? "Sending..." : "Send message"}
      </button>
    </section>
  );
}
