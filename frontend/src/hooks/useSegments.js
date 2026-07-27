import { useState, useCallback } from 'react';

export function useSegments() {
  const [segments, setSegments] = useState([]);
  const [history, setHistory] = useState([]);
  const [activeSegmentIndex, setActiveSegmentIndex] = useState(-1);
  const [cutMode, setCutMode] = useState(false);
  const [isLoopMode, setIsLoopMode] = useState(false);

  const saveToHistory = useCallback(() => {
    setHistory(prev => {
      const newHistory = [...prev, JSON.stringify(segments)];
      if (newHistory.length > 50) newHistory.shift(); // Keep last 50 states
      return newHistory;
    });
  }, [segments]);

  const undo = useCallback(() => {
    if (history.length > 0) {
      const prevSegmentsJSON = history[history.length - 1];
      setSegments(JSON.parse(prevSegmentsJSON));
      setHistory(prev => prev.slice(0, -1));
    }
  }, [history]);

  const updateSegmentText = useCallback((index, newText) => {
    saveToHistory();
    const newSegments = [...segments];
    newSegments[index].text = newText;
    setSegments(newSegments);
  }, [segments, saveToHistory]);

  const mergeSegments = useCallback((index) => {
    if (index >= segments.length - 1) return;
    saveToHistory();
    const newSegments = [...segments];
    // Next segment's end time is used
    newSegments[index].end = newSegments[index + 1].end;
    newSegments[index].text += newSegments[index + 1].text;
    newSegments.splice(index + 1, 1);
    setSegments(newSegments);
  }, [segments, saveToHistory]);

  const smartSplit = useCallback((index) => {
    saveToHistory();
    const s = segments[index];
    const mid = s.start + (s.end - s.start) / 2;
    const midText = Math.floor(s.text.length / 2);
    
    const s1 = { ...s, text: s.text.substring(0, midText), end: mid };
    const s2 = { ...s, text: s.text.substring(midText), start: mid };
    
    const newSegments = [...segments];
    newSegments.splice(index, 1, s1, s2);
    setSegments(newSegments);
  }, [segments, saveToHistory]);

  const deleteSegment = useCallback((index) => {
    saveToHistory();
    const newSegments = [...segments];
    if (cutMode) {
      // Ripple delete: shift all subsequent segments left
      const deletedLength = newSegments[index].end - newSegments[index].start;
      for (let i = index + 1; i < newSegments.length; i++) {
        newSegments[i].start = parseFloat((newSegments[i].start - deletedLength).toFixed(3));
        newSegments[i].end = parseFloat((newSegments[i].end - deletedLength).toFixed(3));
      }
    }
    newSegments.splice(index, 1);
    setSegments(newSegments);
  }, [segments, saveToHistory, cutMode]);

  return {
    segments,
    setSegments,
    history,
    setHistory,
    activeSegmentIndex,
    setActiveSegmentIndex,
    cutMode,
    setCutMode,
    isLoopMode,
    setIsLoopMode,
    saveToHistory,
    undo,
    updateSegmentText,
    mergeSegments,
    smartSplit,
    deleteSegment
  };
}
