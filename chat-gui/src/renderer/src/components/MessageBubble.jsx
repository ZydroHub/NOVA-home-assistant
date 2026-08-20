import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function MessageBubble({ role, text }) {
    const isUser = role === 'user';

    const mainContent = text.replace(/<think>[\s\S]*?(?:<\/think>|$)/gi, '').trim();

    return (
        <div className={`flex animate-message-in ${isUser ? 'justify-end pl-8' : 'justify-start pr-8'}`}>
            <div
                className={`relative max-w-[88%] overflow-hidden rounded-3xl px-5 py-4 font-['Inter'] text-[15px] leading-relaxed shadow-[0_16px_42px_rgba(0,0,0,0.28)] backdrop-blur-md ${isUser
                    ? 'border border-cyan-300/25 bg-cyan-300/[0.12] text-white'
                    : 'border border-white/[0.08] bg-slate-900/[0.48] text-cyan-50'
                    }`}
            >
                <div className={`absolute inset-y-3 w-[3px] rounded-full ${isUser ? 'right-0 bg-cyan-300/70 shadow-[0_0_14px_rgba(26,209,255,0.6)]' : 'left-0 bg-emerald-300/70 shadow-[0_0_14px_rgba(95,244,178,0.55)]'}`} />
                <div className={`mb-3 flex items-center gap-2 text-[0.68rem] font-extrabold uppercase tracking-[0.18em] ${isUser ? 'justify-end text-cyan-100/80' : 'text-emerald-100/75'}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${isUser ? 'order-2 bg-cyan-300 shadow-[0_0_10px_rgba(26,209,255,0.7)]' : 'bg-emerald-300 shadow-[0_0_10px_rgba(95,244,178,0.65)]'}`} />
                    {isUser ? 'You' : 'NOVA'}
                </div>

                <div className={`markdown-content break-words ${isUser ? 'text-white' : 'text-cyan-50/95'}`}>
                    <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                            a: ({ node, ...props }) => (
                                <a
                                    {...props}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-cyan-200 underline decoration-cyan-300/40 decoration-1 underline-offset-4 transition-colors hover:text-white"
                                />
                            ),
                            // Code blocks
                            code: ({ node, inline, className, children, ...props }) => {
                                const match = /language-(\w+)/.exec(className || '');
                                return !inline ? (
                                    <div className="my-3 overflow-hidden rounded-2xl border border-cyan-300/15 bg-black/35">
                                        <div className="border-b border-cyan-300/10 px-3 py-2 font-mono text-xs uppercase tracking-[0.14em] text-cyan-100/65">
                                            {match ? match[1] : 'code'}
                                        </div>
                                        <pre className="overflow-x-auto p-3">
                                            <code className={`font-mono text-sm ${className}`} {...props}>
                                                {children}
                                            </code>
                                        </pre>
                                    </div>
                                ) : (
                                    <code className="rounded-md border border-cyan-300/15 bg-black/30 px-1.5 py-0.5 font-mono text-sm text-cyan-100" {...props}>
                                        {children}
                                    </code>
                                );
                            },
                            // Lists
                            ul: ({ node, ...props }) => (
                                <ul className="my-2 ml-4 list-outside list-square space-y-1" {...props} />
                            ),
                            ol: ({ node, ...props }) => (
                                <ol className="my-2 ml-4 list-outside list-decimal space-y-1" {...props} />
                            ),
                            li: ({ node, ...props }) => (
                                <li className="pl-1 marker:text-cyan-300" {...props} />
                            ),
                            // Headings
                            h1: ({ node, ...props }) => (
                                <h1 className="mb-2 mt-4 text-xl font-black text-white first:mt-0" {...props} />
                            ),
                            h2: ({ node, ...props }) => (
                                <h2 className="mb-2 mt-3 text-lg font-extrabold text-cyan-100 first:mt-0" {...props} />
                            ),
                            h3: ({ node, ...props }) => (
                                <h3 className="mb-1 mt-2 text-base font-bold first:mt-0" {...props} />
                            ),
                            // Paragraphs
                            p: ({ node, ...props }) => (
                                <p className="mb-2 last:mb-0" {...props} />
                            ),
                            // Blockquotes
                            blockquote: ({ node, ...props }) => (
                                <blockquote className="my-3 border-l-2 border-cyan-300/60 bg-white/[0.03] py-2 pl-4 italic text-cyan-100/80" {...props} />
                            ),
                            img: ({ node, ...props }) => (
                                <img {...props} className="rounded-2xl border border-cyan-300/15 shadow-[0_14px_32px_rgba(0,0,0,0.35)]" />
                            )
                        }}
                    >
                        {mainContent}
                    </ReactMarkdown>
                </div>
            </div>
        </div>
    );
}
