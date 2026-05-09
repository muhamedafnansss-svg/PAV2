import { useState } from 'react';
import { motion } from 'framer-motion';
import Header from '../components/Header';
import { queryChat } from '../api/client';

export default function Workspace() {
  const [code, setCode]       = useState('# Paste or write code here...\n');
  const [query, setQuery]     = useState('');
  const [result, setResult]   = useState('');
  const [loading, setLoading] = useState(false);
  const [tab, setTab]         = useState('editor');

  const analyze = async () => {
    if (!code.trim()) return;
    setLoading(true);
    setResult('');
    try {
      const prompt = query.trim()
        ? `${query}\n\n\`\`\`\n${code}\n\`\`\``
        : `Review this code for issues, improvements, and security concerns:\n\n\`\`\`\n${code}\n\`\`\``;
      const data = await queryChat(prompt, 'workspace-session');
      setResult(data.text || '');
      setTab('result');
    } catch (e) {
      setResult(`Error: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-col" style={{ height: '100%' }}>
      <Header title="WORKSPACE — Code Analysis" icon="⬡" color="green" />
      <div className="page-body">
        <div className="grid-2 gap-4 mb-4">
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div className="card-title">Code Editor</div>
            <textarea
              value={code}
              onChange={e => setCode(e.target.value)}
              spellCheck={false}
              style={{
                flex: 1, minHeight: 300, background: '#060d1a', border: '1px solid var(--border-hi)',
                borderRadius: 8, padding: '14px', color: '#a8c4e0', fontSize: 12,
                fontFamily: 'var(--font-mono)', resize: 'vertical', outline: 'none', lineHeight: 1.6,
              }}
            />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Optional: What specifically to analyze? (e.g. 'Find SQL injection vulnerabilities')"
              style={{
                background: 'var(--bg-elevated)', border: '1px solid var(--border-hi)',
                borderRadius: 6, padding: '8px 12px', color: 'var(--text-base)', fontSize: 12,
                fontFamily: 'var(--font-ui)', outline: 'none',
              }}
            />
            <motion.button
              className="btn btn-primary"
              onClick={analyze}
              disabled={loading || !code.trim()}
              whileTap={{ scale: 0.97 }}
              style={{ alignSelf: 'flex-start' }}
            >
              {loading ? '⏳ Analyzing...' : '⬡ Analyze with Qwen 2.5'}
            </motion.button>
          </div>

          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="card-title">Analysis Result</div>
            {loading && (
              <div style={{ color: 'var(--cyan)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
                Qwen 2.5 is analyzing your code...
              </div>
            )}
            {result ? (
              <pre style={{
                flex: 1, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-base)', lineHeight: 1.7,
                overflow: 'auto', maxHeight: 440,
              }}>
                {result}
              </pre>
            ) : !loading && (
              <div className="empty-state">
                <div className="empty-icon">⬡</div>
                <div className="empty-text">Paste code and click Analyze</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
