import { useState, useEffect } from "react";
import { X, Save, RefreshCw, ChevronDown, ChevronUp, Bookmark, Trash2, CheckCircle, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { getConfig, updateConfig, scanModels } from "../lib/api";
import styles from "./ConfigModal.module.css";

interface ConfigModalProps {
    isOpen: boolean;
    onClose: () => void;
}

interface Preset {
    name: string;
    smartHost: string;
    smartModel: string;
    fastHost: string;
    fastModel: string;
}

export default function ConfigModal({ isOpen, onClose }: ConfigModalProps) {
    const [loading, setLoading] = useState(false);
    const [saved, setSaved] = useState(false); // Success state
    const [configMode, setConfigMode] = useState<"default" | "custom">("default");

    // Custom Mode State
    const [scanningSmart, setScanningSmart] = useState(false);
    const [scanningFast, setScanningFast] = useState(false);

    // Form State
    const [smartHost, setSmartHost] = useState("");
    const [fastHost, setFastHost] = useState("");
    const [smartModel, setSmartModel] = useState("");
    const [fastModel, setFastModel] = useState("");

    // Available Models
    const [smartModels, setSmartModels] = useState<string[]>([]);
    const [fastModels, setFastModels] = useState<string[]>([]);
    const [embeddingModels, setEmbeddingModels] = useState<string[]>([]);

    // Embedding Model State
    const [embeddingHost, setEmbeddingHost] = useState("http://localhost:11434");
    const [embeddingModel, setEmbeddingModel] = useState("nomic-embed-text");
    const [scanningEmbedding, setScanningEmbedding] = useState(false);
    const [showEmbeddingAdvanced, setShowEmbeddingAdvanced] = useState(false);

    const [showAdvanced, setShowAdvanced] = useState(false);

    // Presets
    const [presets, setPresets] = useState<Preset[]>([]);
    const [newPresetName, setNewPresetName] = useState("");
    const [verifyingPreset, setVerifyingPreset] = useState(false);
    const [verificationError, setVerificationError] = useState<string | null>(null);

    useEffect(() => {
        if (isOpen) {
            setSaved(false); // Reset saved state on open
            loadConfig();
            loadPresets();
        }
    }, [isOpen]);

    function loadPresets() {
        if (typeof window !== 'undefined') {
            const stored = localStorage.getItem("agent_config_presets");
            if (stored) {
                try {
                    setPresets(JSON.parse(stored));
                } catch (e) { console.error("Bad presets", e); }
            }
        }
    }

    function savePreset() {
        if (!newPresetName.trim()) return;

        const newPreset: Preset = {
            name: newPresetName,
            smartHost,
            smartModel,
            fastHost: fastHost || smartHost, // Default to smart host if empty
            fastModel
        };

        const updated = [...presets, newPreset];
        setPresets(updated);
        localStorage.setItem("agent_config_presets", JSON.stringify(updated));
        setNewPresetName("");
    }

    function deletePreset(index: number) {
        const updated = presets.filter((_, i) => i !== index);
        setPresets(updated);
        localStorage.setItem("agent_config_presets", JSON.stringify(updated));
    }

    async function handleLoadPreset(e: React.ChangeEvent<HTMLSelectElement>) {
        const idx = parseInt(e.target.value);
        if (isNaN(idx)) return;

        const p = presets[idx];
        if (!p) return;

        setVerifyingPreset(true);
        setVerificationError(null);

        // VERIFY FIRST feature
        try {
            // Check Smart Host
            const sModels = await scanModels(p.smartHost);
            if (!sModels || sModels.length === 0) throw new Error(`Could not connect to Smart Host: ${p.smartHost}`);
            if (!sModels.includes(p.smartModel)) throw new Error(`Model ${p.smartModel} not found on Smart Host`);

            // Check Fast Host (if different)
            let fModels = sModels;
            if (p.fastHost && p.fastHost !== p.smartHost) {
                fModels = await scanModels(p.fastHost);
                if (!fModels || fModels.length === 0) throw new Error(`Could not connect to Fast Host: ${p.fastHost}`);
            }
            if (!fModels.includes(p.fastModel)) throw new Error(`Model ${p.fastModel} not found on Fast Host`);

            // If verified, apply
            setSmartHost(p.smartHost);
            setSmartModels(sModels);
            setSmartModel(p.smartModel);

            setFastHost(p.fastHost);
            setFastModels(fModels);
            setFastModel(p.fastModel);

            // Expand advanced if hosts differ
            setShowAdvanced(p.fastHost !== p.smartHost);

        } catch (err: any) {
            console.error("Verification failed", err);
            setVerificationError(err.message || "Verification Failed");
        } finally {
            setVerifyingPreset(false);
        }
    }

    async function loadConfig() {
        const data = await getConfig();
        if (data) {
            // Set Hosts
            const sHost = data.hosts.primary || "http://localhost:11434";
            const fHost = data.hosts.fast || sHost;
            const sModel = data.models.smart;
            const fModel = data.models.fast;

            setSmartHost(sHost);
            setFastHost(fHost);
            setSmartModel(sModel);
            setFastModel(fModel);

            // Embedding config
            const eHost = data.hosts.embedding || "http://localhost:11434";
            const eModel = data.models.embedding || "nomic-embed-text";
            setEmbeddingHost(eHost);
            setEmbeddingModel(eModel);

            // Set visibility flags
            setShowAdvanced(fHost !== sHost);
            setShowEmbeddingAdvanced(eHost !== sHost);

            // Heuristic for default mode
            const isDefault = sHost === "http://10.20.39.12:11434" && sModel === "qwen2.5:72b-instruct" &&
                fHost === "http://10.20.39.12:11434" && fModel === "qwen2.5:72b-instruct";

            setConfigMode(isDefault ? "default" : "custom");

            // Background scan for custom mode data if needed
            scan(sHost, (m) => { setSmartModels(m); setFastModels(m); }, setScanningSmart);
        }
    }

    async function scan(host: string, setList: (m: string[]) => void, setLoadingState: (b: boolean) => void) {
        if (!host) return;
        setLoadingState(true);
        // Timeout scan to avoid hanging
        try {
            const models = await Promise.race([
                scanModels(host),
                new Promise<string[]>((_, reject) => setTimeout(() => reject("timeout"), 5000))
            ]);
            setList(models);
        } catch (e) {
            console.warn("Scan failed or timed out", e);
        } finally {
            setLoadingState(false);
        }
    }

    const [saveStatus, setSaveStatus] = useState<"idle" | "validating" | "applying" | "success" | "error">("idle");
    const [saveError, setSaveError] = useState<string | null>(null);

    async function handleSave() {
        setSaveStatus("validating");
        setSaveError(null);

        try {
            // Determine effective hosts based on UI state
            const effectiveFastHost = showAdvanced ? fastHost : smartHost;
            const effectiveEmbeddingHost = showEmbeddingAdvanced ? embeddingHost : smartHost;

            // 1. Validation Phase
            // Only validate in custom mode
            if (configMode === "custom") {
                // Helper for matching models with tags
                const checkModel = (list: string[], target: string) => {
                    return list.some(m => m === target || m === `${target}:latest` || m.startsWith(`${target}:`));
                };

                // Check Smart Host
                const sModels = await scanModels(smartHost);
                if (!sModels || sModels.length === 0) throw new Error(`Could not connect to Smart Host: ${smartHost}`);
                if (!checkModel(sModels, smartModel)) throw new Error(`Model ${smartModel} not found on Smart Host`);

                // Check Fast Host
                if (effectiveFastHost !== smartHost) {
                    const fModels = await scanModels(effectiveFastHost);
                    if (!fModels || fModels.length === 0) throw new Error(`Could not connect to Fast Host: ${effectiveFastHost}`);
                    if (!checkModel(fModels, fastModel)) throw new Error(`Model ${fastModel} not found on Fast Host`);
                } else {
                    // Shared host
                    if (!checkModel(sModels, fastModel)) throw new Error(`Model ${fastModel} not found on Host`);
                }

                // Check Embedding Host
                let eModels = sModels;
                if (effectiveEmbeddingHost !== smartHost) {
                    eModels = await scanModels(effectiveEmbeddingHost);
                    if (!eModels || eModels.length === 0) throw new Error(`Could not connect to Embedding Host: ${effectiveEmbeddingHost}`);
                }

                if (!checkModel(eModels, embeddingModel)) {
                    if (embeddingModel === 'nomic-embed-text') {
                        throw new Error(`Model 'nomic-embed-text' not found. Please run 'ollama pull nomic-embed-text' on ${effectiveEmbeddingHost}`);
                    }
                    throw new Error(`Model ${embeddingModel} not found on Embedding Host`);
                }
            }

            // 2. Applying Phase
            setSaveStatus("applying");

            const configUpdate = configMode === "default" ? {
                smart_model: "qwen2.5:72b-instruct",
                fast_model: "qwen2.5:72b-instruct",
                llm_host: "http://10.20.39.12:11434",
                fast_llm_host: "http://10.20.39.12:11434"
            } : {
                smart_model: smartModel,
                fast_model: fastModel,
                llm_host: smartHost,
                fast_llm_host: effectiveFastHost,
                embedding_model: embeddingModel,
                embedding_host: effectiveEmbeddingHost
            };

            // Force a minimum delay for "Applying..." visibility (UX)
            await Promise.all([
                updateConfig(configUpdate),
                new Promise(r => setTimeout(r, 800))
            ]);

            // 3. Success
            setSaveStatus("success");
            toast.success("Configuration saved and applied!");

            // Wait for animation then close
            setTimeout(() => {
                onClose();
                setSaveStatus("idle");
            }, 1500);

        } catch (e: any) {
            console.error("Failed to save config", e);
            setSaveStatus("error");
            setSaveError(e.message || "Failed to save configuration");
        }
    }

    if (!isOpen) return null;

    return (
        <div className={styles.overlay}>
            <div className={styles.modal}>
                <div className={styles.header}>
                    <h2>Agent Configuration</h2>
                    <button onClick={onClose} className={styles.closeBtn}><X size={20} /></button>
                </div>

                <div className={styles.modeToggle}>
                    <button
                        className={`${styles.modeBtn} ${configMode === "default" ? styles.activeMode : ""}`}
                        onClick={() => setConfigMode("default")}
                    >
                        Default (Remote)
                    </button>
                    <button
                        className={`${styles.modeBtn} ${configMode === "custom" ? styles.activeMode : ""}`}
                        onClick={() => setConfigMode("custom")}
                    >
                        Custom Config
                    </button>
                </div>

                <div className={styles.body}>
                    {configMode === "default" ? (
                        <div className={styles.defaultCard}>
                            <div className={styles.defaultTitle}>✅ Standard Remote Configuration</div>
                            <div className={styles.defaultDesc}>
                                Both Agents (Smart & Fast) will use the shared high-performance remote server.
                            </div>
                            <div className={styles.defaultDetail}>
                                <div><strong>Host:</strong> http://10.20.39.12:11434</div>
                                <div><strong>Model:</strong> qwen2.5:72b-instruct</div>
                            </div>
                        </div>
                    ) : (
                        <>
                            {/* CUSTOM MODE UI */}

                            {/* PRESET MANAGER */}
                            <div className={styles.presetContainer}>
                                <div className={styles.presetHeader}>Saved Presets</div>
                                <div className={styles.presetRow}>
                                    <select className={styles.presetSelect} onChange={handleLoadPreset} defaultValue="">
                                        <option value="" disabled>Load a verified preset...</option>
                                        {presets.map((p, i) => (
                                            <option key={i} value={i}>{p.name} ({p.smartModel})</option>
                                        ))}
                                    </select>

                                    {/* No delete yet via UI to keep it simple, or maybe obscure it? 
                                        Actually user asked for "save", "select". Delete is implied good UX.
                                        Let's add basic delete for current list.
                                    */}
                                </div>

                                {verificationError && (
                                    <div style={{ color: 'var(--error-color)', fontSize: '0.8rem', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                        <AlertTriangle size={12} /> {verificationError}
                                    </div>
                                )}

                                {verifyingPreset && (
                                    <div style={{ color: 'var(--accent-primary)', fontSize: '0.8rem', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                        <RefreshCw size={12} className="animate-spin" /> Verifying connection...
                                    </div>
                                )}

                                <div className={styles.savePresetRow}>
                                    <input
                                        className={styles.savePresetInput}
                                        placeholder="Save current settings as..."
                                        value={newPresetName}
                                        onChange={e => setNewPresetName(e.target.value)}
                                    />
                                    <button className={styles.presetBtn} onClick={savePreset} title="Save Preset">
                                        <Bookmark size={14} />
                                    </button>
                                </div>
                            </div>

                            <div className={styles.sectionHeader}>🧠 Smart Agent (Reasoning)</div>
                            <div className={styles.card}>
                                <div className={styles.group}>
                                    <label>Host URL</label>
                                    <div className={styles.inputRow}>
                                        <input value={smartHost} onChange={e => setSmartHost(e.target.value)} placeholder="http://localhost:11434" />
                                        <button className={styles.scanBtn} onClick={() => scan(smartHost, setSmartModels, setScanningSmart)} disabled={scanningSmart}>
                                            <RefreshCw size={14} className={scanningSmart ? "animate-spin" : ""} />
                                        </button>
                                    </div>
                                </div>

                                <div className={styles.group}>
                                    <label>Model</label>
                                    <div className={styles.inputRow}>
                                        <select value={smartModel} onChange={e => setSmartModel(e.target.value)}>
                                            <option value="" disabled>Select a model</option>
                                            {smartModels.map(m => <option key={m} value={m}>{m}</option>)}
                                        </select>
                                    </div>
                                </div>
                            </div>

                            <div className={styles.divider} />

                            <div className={styles.sectionHeader}>⚡ Fast Agent (Chat)</div>
                            <div className={styles.card}>
                                <div className={styles.group}>
                                    <div className={styles.rowBetween}>
                                        <label>Use Different Host?</label>
                                        <button className={styles.toggleLink} onClick={() => setShowAdvanced(!showAdvanced)}>
                                            {showAdvanced ? "Hide Host" : "Configure Host"}
                                        </button>
                                    </div>

                                    {showAdvanced && (
                                        <div className={styles.inputRow} style={{ marginTop: "8px" }}>
                                            <input value={fastHost} onChange={e => setFastHost(e.target.value)} placeholder="http://localhost:11434" />
                                            <button className={styles.scanBtn} onClick={() => scan(fastHost, setFastModels, setScanningFast)} disabled={scanningFast}>
                                                <RefreshCw size={14} className={scanningFast ? "animate-spin" : ""} />
                                            </button>
                                        </div>
                                    )}
                                </div>

                                <div className={styles.group}>
                                    <label>Model</label>
                                    <div className={styles.inputRow}>
                                        <select value={fastModel} onChange={e => setFastModel(e.target.value)}>
                                            <option value="" disabled>Select a model</option>
                                            {(showAdvanced ? fastModels : smartModels).map(m => <option key={m} value={m}>{m}</option>)}
                                        </select>
                                    </div>
                                </div>
                            </div>

                            <div className={styles.divider} />

                            <div className={styles.sectionHeader}>🔍 Embedding Model (RAG & Semantic Search)</div>
                            <div className={styles.card}>
                                <div className={styles.group}>
                                    <div className={styles.rowBetween}>
                                        <label>Use Different Host?</label>
                                        <button className={styles.toggleLink} onClick={() => setShowEmbeddingAdvanced(!showEmbeddingAdvanced)}>
                                            {showEmbeddingAdvanced ? "Hide Host" : "Configure Host"}
                                        </button>
                                    </div>

                                    {showEmbeddingAdvanced && (
                                        <div className={styles.inputRow} style={{ marginTop: "8px" }}>
                                            <input value={embeddingHost} onChange={e => setEmbeddingHost(e.target.value)} placeholder="http://localhost:11434" />
                                            <button className={styles.scanBtn} onClick={() => scan(embeddingHost, setEmbeddingModels, setScanningEmbedding)} disabled={scanningEmbedding}>
                                                <RefreshCw size={14} className={scanningEmbedding ? "animate-spin" : ""} />
                                            </button>
                                        </div>
                                    )}
                                </div>

                                <div className={styles.group}>
                                    <label>Model <span style={{ color: 'var(--text-tertiary)', fontSize: '0.75rem' }}>(nomic-embed-text recommended)</span></label>
                                    <div className={styles.inputRow}>
                                        <select value={embeddingModel} onChange={e => setEmbeddingModel(e.target.value)}>
                                            <option value="" disabled>Select a model</option>
                                            <option value="nomic-embed-text">nomic-embed-text (recommended)</option>
                                            <option value="mxbai-embed-large">mxbai-embed-large</option>
                                            <option value="all-minilm">all-minilm</option>
                                            {(showEmbeddingAdvanced ? embeddingModels : smartModels).filter(m => !['nomic-embed-text', 'mxbai-embed-large', 'all-minilm'].includes(m)).map(m => <option key={m} value={m}>{m}</option>)}
                                        </select>
                                    </div>
                                </div>
                                <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: '8px' }}>
                                    💡 Tip: Run <code style={{ background: 'var(--bg-tertiary)', padding: '2px 6px', borderRadius: '4px' }}>ollama pull nomic-embed-text</code> locally for fastest embeddings.
                                </div>
                            </div>
                        </>
                    )}
                </div>

                <div className={styles.footer}>
                    <div style={{ flex: 1, marginRight: '16px' }}>
                        {saveError && (
                            <div style={{ color: 'var(--error-color)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <AlertTriangle size={14} /> {saveError}
                            </div>
                        )}
                    </div>

                    <button
                        className={styles.saveBtn}
                        onClick={handleSave}
                        disabled={saveStatus !== "idle" && saveStatus !== "error"}
                        style={{ minWidth: "160px", justifyContent: "center" }}
                    >
                        {saveStatus === "idle" || saveStatus === "error" ? (
                            <><Save size={16} /> Save & Apply</>
                        ) : saveStatus === "validating" ? (
                            <><RefreshCw size={16} className="animate-spin" /> Checking...</>
                        ) : saveStatus === "applying" ? (
                            <><RefreshCw size={16} className="animate-spin" /> Applying...</>
                        ) : (
                            <><CheckCircle size={16} /> Saved!</>
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
}
