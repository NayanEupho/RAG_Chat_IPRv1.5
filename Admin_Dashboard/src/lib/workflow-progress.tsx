'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

export interface WorkflowProgressState {
  active: boolean;
  progress: number;
  stage: string;
  detail: string;
  tone: 'info' | 'success' | 'warning' | 'danger';
  selectedPaths: string[];
}

export interface ActivityNotification extends WorkflowProgressState {
  id: string;
  createdAt: string;
  pinned?: boolean;
}

const DEFAULT_STATE: WorkflowProgressState = {
  active: false,
  progress: 0,
  stage: 'Idle',
  detail: '',
  tone: 'info',
  selectedPaths: [],
};

interface WorkflowProgressContextValue {
  state: WorkflowProgressState;
  notifications: ActivityNotification[];
  updateProgress: (next: Partial<WorkflowProgressState>) => void;
  pushNotification: (next: Partial<WorkflowProgressState> & { stage: string; detail: string }) => void;
  dismissNotification: (id: string) => void;
  clearNotifications: () => void;
  resetProgress: () => void;
}

const STORAGE_KEY = 'admin-dashboard-workflow-progress-v2';
const WorkflowProgressContext = createContext<WorkflowProgressContextValue | null>(null);

function makeNotification(next: Partial<WorkflowProgressState> & { stage: string; detail: string }): ActivityNotification {
  return {
    id: `note_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
    active: next.active ?? true,
    progress: next.progress ?? 0,
    stage: next.stage,
    detail: next.detail,
    tone: next.tone ?? 'info',
    selectedPaths: next.selectedPaths ?? [],
    pinned: next.tone === 'danger',
  };
}

export function WorkflowProgressProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<WorkflowProgressState>(DEFAULT_STATE);
  const [notifications, setNotifications] = useState<ActivityNotification[]>([]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw);
      setState({ ...DEFAULT_STATE, ...(parsed.state || {}) });
      setNotifications(Array.isArray(parsed.notifications) ? parsed.notifications : []);
    } catch {
      window.sessionStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ state, notifications }));
  }, [state, notifications]);

  const updateProgress = useCallback((next: Partial<WorkflowProgressState>) => {
    setState(current => ({ ...current, ...next, active: next.active ?? true }));
    if ((next.stage || next.detail) && next.tone !== 'info') {
      setNotifications(current => [makeNotification({
        stage: next.stage || current[0]?.stage || 'Update',
        detail: next.detail || '',
        progress: next.progress,
        tone: next.tone,
        selectedPaths: next.selectedPaths,
      }), ...current].slice(0, 30));
    }
  }, []);

  const pushNotification = useCallback((next: Partial<WorkflowProgressState> & { stage: string; detail: string }) => {
    setNotifications(current => [makeNotification(next), ...current].slice(0, 50));
  }, []);

  const dismissNotification = useCallback((id: string) => {
    setNotifications(current => current.filter(item => item.id !== id));
  }, []);

  const clearNotifications = useCallback(() => {
    setNotifications([]);
  }, []);

  const resetProgress = useCallback(() => {
    setState(DEFAULT_STATE);
  }, []);

  const value = useMemo(
    () => ({ state, notifications, updateProgress, pushNotification, dismissNotification, clearNotifications, resetProgress }),
    [state, notifications, updateProgress, pushNotification, dismissNotification, clearNotifications, resetProgress],
  );
  return <WorkflowProgressContext.Provider value={value}>{children}</WorkflowProgressContext.Provider>;
}

export function useWorkflowProgress() {
  const context = useContext(WorkflowProgressContext);
  if (!context) {
    throw new Error('useWorkflowProgress must be used within WorkflowProgressProvider');
  }
  return context;
}
