
import React, { useState, useEffect, useRef, useCallback } from 'react';
import '../index.css';
import { Settings, Search, X, Loader } from 'lucide-react';
import AIAssistant from '../components/AIAssistant';
import DirectorWizard from '../components/DirectorWizard';
import SceneTimeline from '../components/SceneTimeline';
import ImageDirector from '../components/ImageDirector';
import Boardroom from '../components/Boardroom'; // Trinity DashboardWizard';
import SoulPassport from '../components/SoulPassport';
import CollaborativePanel from '../components/CollaborativePanel';
import QualityGate from '../components/QualityGate';
import SettingsPage from '../components/SettingsPage';
import ProductionPipeline from '../components/ProductionPipeline';
import ProductionWizard from '../components/ProductionWizard';   // D-1: 仕上げウィザード
import QuickDecisionBar from '../components/QuickDecisionBar';   // R-2: ステップ⑤
import StepReviewPanel from '../components/StepReviewPanel';     // R-3: ステップ⑦
import ThemeSelector from '../components/ThemeSelector';         // R-4: ステップ④.5
import WelcomeOnboarding from '../components/WelcomeOnboarding'; // P0-2: 初回オンボーディング
import { apiFetch, apiUrl } from '../gateway/client.js';


export default function EditorPage() {
  const [segments, setSegments] = useState([]);
  const [history, setHistory] = useState([]);
  const [currentTime, setCurrentTime] = useState(0);
  const [activeSegmentIndex, setActiveSegmentIndex] = useState(-1);
  const [isRendering, setIsRendering] = useState(false);
  const [suggestions, setSuggestions] = useState([]); // AI Partner Suggestions
  const [showWizard, setShowWizard] = useState(false); // AI Director Wizard
  const [scenes, setScenes] = useState([]); // Generated Scenes
  const [audioConfig, setAudioConfig] = useState(null); // Audio Config (BGM)
  const [editMode, setEditMode] = useState('subtitle'); // 'subtitle' | 'director'
  const [view, setView] = useState('settings'); // 'editor' | 'settings'
  const videoRef = useRef(null);
  const listRef = useRef(null);

  // Search & Replace State
  const [showSearch, setShowSearch] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [replaceText, setReplaceText] = useState('');

  // NLE (Non-Linear Editing) State
  const [cutMode, setCutMode] = useState(false); // If true, "Delete" becomes "Ripple Delete"
  const [isLoopMode, setIsLoopMode] = useState(false); // Smart Focus Loop
  const [subtitleStyle, setSubtitleStyle] = useState('default'); // 'default' | 'youtuber' | 'cinematic' | 'cute'
  // Subtitle Vertical Offset (Manual Adjustment)
  const [subtitleY, setSubtitleY] = useState(0); // Y offset in pixels
  const [subtitleScale, setSubtitleScale] = useState(1.0); // Font scale
  const [targetChars, setTargetChars] = useState(13); // Rhythm Target
  const [showShortcuts, setShowShortcuts] = useState(false); // Shortcut Guide
  const [timeMap, setTimeMap] = useState([]); // Stores { start, end, offset } for virtual timeline
  const [virtualDuration, setVirtualDuration] = useState(0);

  // Resizable Panel Logic
  const [rightPanelWidth, setRightPanelWidth] = useState(500);
  const [isResizing, setIsResizing] = useState(false);
  const [isBoardroomOpen, setIsBoardroomOpen] = useState(false); // Trinity Boardroom State
  const [videoTimestamp, setVideoTimestamp] = useState(Date.now());

  // Boardroom State
  const [showBoardroom, setShowBoardroom] = useState(false); // Trinity Boardroom State
  const [showSoulPassport, setShowSoulPassport] = useState(false); // Trinity Soul Passport State
  const [showCollaborativePanel, setShowCollaborativePanel] = useState(false); // Collaborative Studio State
  const [currentRole, setCurrentRole] = useState('admin'); // 'admin' | 'owner'
  const [boardroomQuery, setBoardroomQuery] = useState(""); // Agenda from Director
  const [showPreview, setShowPreview] = useState(true); // Assuming this is needed for the button in the header
  const [showDirectorOverlay, setShowDirectorOverlay] = useState(true);

  // Quality Gate State
  const [showQualityGate, setShowQualityGate] = useState(false);
  const [qualityGateData, setQualityGateData] = useState(null);
  const [isVerifying, setIsVerifying] = useState(false);

  // Pipeline State
  const [showPipeline, setShowPipeline] = useState(false);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineStageName, setPipelineStageName] = useState('');

  // ━━━ R-2: QuickDecision State ━━━
  const [showQuickDecision, setShowQuickDecision] = useState(false);
  const [quickDecisionItems, setQuickDecisionItems] = useState([]);

  // ━━━ R-3: StepReview State ━━━
  const [showStepReview, setShowStepReview] = useState(false);
  const [stepReviewData, setStepReviewData] = useState(null);

  // ━━━ R-4: ThemeSelector State ━━━
  const [showThemeSelector, setShowThemeSelector] = useState(false);

  // ━━━ D-1: ProductionWizard State ━━━
  const [showProductionWizard, setShowProductionWizard] = useState(false);
  const [wizardContext, setWizardContext] = useState(null);

  // ━━━ Phase 1: ツールメニュー State ━━━
  const [showToolMenu, setShowToolMenu] = useState(false);

  // ━━━ P0-2: オンボーディング State ━━━
  const [showOnboarding, setShowOnboarding] = useState(
    () => !localStorage.getItem('antigravity_onboarded')
  );

  // Pipeline status polling (header indicator)
  const prevPipelineStatusRef = useRef(null);
  useEffect(() => {
    const checkPipeline = () => {
      apiFetch('getPipelineStatus')
        .then(r => r.json())
        .then(d => {
          const running = d.status === 'running';
          setPipelineRunning(running);
          if (running) {
            const active = d.stages?.find(s => s.status === 'running');
            setPipelineStageName(active ? active.name : '');
          } else if (d.status === 'completed') {
            setPipelineRunning(false);
            setPipelineStageName('完了');
            // D-1: パイプライン完了時にモーダルを自動表示
            if (prevPipelineStatusRef.current === 'running') {
              setShowPipeline(true);
            }
            setTimeout(() => setPipelineStageName(''), 5000);
          }
          prevPipelineStatusRef.current = d.status;
        })
        .catch(() => {});
    };
    checkPipeline();
    const interval = setInterval(checkPipeline, 3000);
    return () => clearInterval(interval);
  }, []);


  // Update video timestamp when entering editor view to ensure fresh content
  useEffect(() => {
    if (view === 'editor') {
      setVideoTimestamp(Date.now());
    }
  }, [view]);

  const startResizing = useCallback(() => setIsResizing(true), []);
  const stopResizing = useCallback(() => setIsResizing(false), []);

  const resize = useCallback((mouseMoveEvent) => {
    if (isResizing) {
      const newWidth = window.innerWidth - mouseMoveEvent.clientX;
      if (newWidth > 300 && newWidth < window.innerWidth * 0.8) {
        setRightPanelWidth(newWidth);
      }
    }
  }, [isResizing]);

  useEffect(() => {
    window.addEventListener("mousemove", resize);
    window.addEventListener("mouseup", stopResizing);

    // Global Key Listener
    const handleGlobalData = (e) => {
      if (e.key === '?' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
        setShowShortcuts(prev => !prev);
      }
      if (e.key === 'Escape') {
        setShowShortcuts(false);
        setShowSearch(false);
        setShowWizard(false);
      }
    };
    window.addEventListener("keydown", handleGlobalData);

    return () => {
      window.removeEventListener("mousemove", resize);
      window.removeEventListener("mouseup", stopResizing);
      window.removeEventListener("keydown", handleGlobalData);
    };
  }, [resize, stopResizing]);

  // Load Segments (with cache busting)
  useEffect(() => {
    // 1. Load Subtitles
    apiFetch('getSegments', { query: { t: videoTimestamp } })
      .then(res => res.json())
      .then(data => {
        const formatted = data.map(s => ({
          ...s,
          sourceStart: s.sourceStart ?? s.start,
          sourceEnd: s.sourceEnd ?? s.end
        }));
        setSegments(formatted);
      })
      .catch(err => console.error("Failed to load segments:", err));

    // 2. Load Director State (Scenes & Audio)
    apiFetch('getDirectorState', { query: { t: videoTimestamp } })
      .then(res => res.json())
      .then(data => {
        if (data.scenes) setScenes(data.scenes);
        if (data.audioConfig) setAudioConfig(data.audioConfig);
      })
      .catch(err => console.error("Failed to load director state:", err));

  }, [videoTimestamp]);

  // AI Context Analyzer
  useEffect(() => {
    if (segments.length === 0) return;

    const newSuggestions = [];

    // 1. Check for Silence Gaps > 1.0s
    for (let i = 0; i < segments.length - 1; i++) {
      const currentEnd = segments[i].end;
      const nextStart = segments[i + 1].start;
      const gap = nextStart - currentEnd;

      if (gap > 1.0) {
        newSuggestions.push({
          id: `gap-${i}`,
          type: 'warning',
          message: `字幕${i + 1}と${i + 2}の間に ${gap.toFixed(1)}秒 の無音があります。カットして詰めますか？`,
          actionLabel: "間を詰める",
          data: { type: 'CLOSE_GAP', index: i, gap: gap },
          segmentIndex: i
        });
      }
    }

    // 2. Check for Long Subtitles > 30 chars
    segments.forEach((s, i) => {
      if (s.text.length > 30) {
        newSuggestions.push({
          id: `long-${i}`,
          type: 'info',
          message: `長い字幕 (${s.text.length}文字) を検出しました。AIで分割しますか？`,
          context: s.text,
          actionLabel: "AIで分割",
          data: { type: 'SPLIT', index: i },
          segmentIndex: i
        });
      }
    });

    // 3. Filler Detection (Proofreading)
    segments.forEach((s, i) => {
      // Detect fillers at start: えー, あの, んー, えっと + optional punctuation
      const match = s.text.match(/^(えー+|あの+|んー+|えっと+)[、。]?/);
      if (match) {
        newSuggestions.push({
          id: `filler-${i}`,
          type: 'warning',
          message: `フィラー「${match[0]}」を検出しました。削除して品質を高めませんか？`,
          context: s.text,
          actionLabel: "修正(削除)",
          data: { type: 'REMOVE_FILLER', index: i, text: match[0] },
          segmentIndex: i
        });
      }

      // 4. Grammar Check: Incomplete Sentences (Ends with particle)
      if (/[はがをにへともので]$/.test(s.text)) {
        newSuggestions.push({
          id: `grammar-${i}`,
          type: 'warning',
          message: `文末が助詞「${s.text.slice(-1)}」で終わっています。文が途切れていませんか？`,
          context: s.text,
          // Removed redundant "Ignore" action.
          // Option: Suggest "Merge with Next" logic
          actionLabel: (i < segments.length - 1) ? "下の行と結合" : null,
          data: { type: (i < segments.length - 1) ? 'MERGE_NEXT' : 'IGNORE', index: i },
          segmentIndex: i
        });
      }
    });

    setSuggestions(newSuggestions);

  }, [segments]);

  // AI Action Handler
  const handleSuggestionAction = (suggestion) => {
    const { type, index, gap } = suggestion.data;

    if (type === 'CLOSE_GAP') {
      // Close the gap by shifting all subsequent segments left
      saveToHistory();
      const newSegments = [...segments];
      // We want next segment to start at current segment end.
      // Shift amount = gap.
      // Shift segments from index + 1 onwards.
      for (let k = index + 1; k < newSegments.length; k++) {
        newSegments[k].start = parseFloat((newSegments[k].start - gap).toFixed(3));
        newSegments[k].end = parseFloat((newSegments[k].end - gap).toFixed(3));
      }
      setSegments(newSegments);
      // Suggestion will disappear on next render as gap is gone
    }

    if (type === 'SPLIT') {
      smartSplit(index);
    }

    if (type === 'MERGE_NEXT') {
      // Calls existing mergeSegments function
      mergeSegments(index);
    }

    if (type === 'REMOVE_FILLER') {
      saveToHistory();
      const newSegments = [...segments];
      const filler = suggestion.data.text;
      if (newSegments[index].text.startsWith(filler)) {
        newSegments[index].text = newSegments[index].text.substring(filler.length);
        setSegments(newSegments);
      }
    }
  };

  const jumpToSegment = (index) => {
    const s = segments[index];
    if (s) {
      // 1. Update Video Time
      if (videoRef.current) {
        // Map virtual start time to source time if simpler, or just set current time
        // Our video player seems to use Virtual Time > Source Time mapping in handleTimeUpdate.
        // But setting video.currentTime requires SOURCE time.
        // We have s.sourceStart.
        const targetTime = s.sourceStart ?? s.start;
        videoRef.current.currentTime = targetTime;
      }
      setCurrentTime(s.start);
      setActiveSegmentIndex(index);

      // 2. Scroll to element & Focus
      // Use ID selector for more robustness than index
      const card = document.getElementById(`segment-${index}`);
      console.log(`[Jump] Target ID: segment-${index}, Found:`, !!card);

      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });

        // Focus the textarea for immediate editing
        const textarea = card.querySelector('textarea');
        if (textarea) {
          textarea.focus({ preventScroll: true });
        }
      } else {
        console.warn(`[Jump] Element segment-${index} not found in DOM.`);
      }
    } else {
      console.warn(`[Jump] Segment index ${index} out of bounds or undefined.`);
    }
  };


  const dismissSuggestion = (id, suggestion) => {
    console.log('[Action] Dismiss/Action triggered:', id, suggestion);
    if (id === 'jump' && suggestion) {
      // Jump to the segment
      if (suggestion.segmentIndex !== undefined) {
        console.log('[Action] Jumping to segment:', suggestion.segmentIndex);
        jumpToSegment(suggestion.segmentIndex);
      } else {
        console.error('[Action] segmentIndex is MISSING in suggestion object!', suggestion);
      }
      return; // Do not dismiss the card
    }
    setSuggestions(prev => prev.filter(s => s.id !== id));
  };

  // Time Mapping Logic (Phase 2.1)
  // Calculates the mapping between Original Video (Source) and Virtual Timeline (Preview)
  const calculateTimeMap = (currentSegments) => {
    // 1. Identify "Deleted Ranges" based on gaps between segments?
    // Actually, in our current logic, we DON'T strictly track deleted ranges. 
    // We track "Kept Segments". 
    // BUT, for Phase 2.1, we need to know what to skip.
    // "Ripple Delete" in Phase 2 MODIFIED the segment.start/end. 
    // It did NOT modify sourceStart/sourceEnd.
    // So, the "Virtual Timeline" is simply the continuous timeline of all segments.
    // WARNING: Gaps between subtitles in normal mode are NOT cuts.
    // We need to differentiate "Cut Gaps" from "Silence Gaps".
    //
    // Correction: Phase 2 logic said "Ripple Delete: Shift all subsequent segments left".
    // This means the timeline (segments.start/end) IS the Virtual Timeline for the cut video.
    // EXCEPT for the gaps *between* subtitles that were NOT cut.
    //
    // WAIT. The user wants to see the "Cut" effect.
    // If I delete a segment in "Cut Mode", the segment is GONE.
    // The timeline shifts.
    // So the "Virtual Timeline" is defined by:
    // - The time from 0 to LastSegment.end.
    // - BUT, what about the video capability?
    // The browser <video> plays the SOURCE.
    // We need to map Virtual Time T -> Source Time S.

    // Let's rebuild the map based on 'sourceStart' / 'sourceEnd' of the CURRENT segments.
    // We assume the segments are sorted by time.
    // If segments are:
    // S1: 0-5 (source 0-5)
    // S2: 5-8 (source 10-13)  <- Gap of 5s in source (5-10 was cut)
    //
    // Map:
    // Virtual 0-5 -> Source 0-5
    // Virtual 5-8 -> Source 10-13

    const map = [];
    let currentVirtual = 0;

    // Sort segments by 'start' (timeline time)
    const sorted = [...currentSegments].sort((a, b) => a.start - b.start);

    if (sorted.length === 0) return { map: [], duration: 0 };

    // We need to handle the "gaps" that are NOT cuts (silence).
    // Ideally, in "Cut Mode", we shouldn't have unintentional gaps?
    // Or rather, we infer that:
    // Virtual Time moves continuously.
    // If S1.end < S2.start, that represents SILENCE that is KEPT.
    // So S1.sourceEnd -> S2.sourceStart should match the gap duration?
    // If it doesn't match, that means a Cut happened there?

    // SIMPLIFICATION for "Video Cut Mode":
    // We assume the User wants to preview the concatenation of ALL Segments + Gaps.
    // Actually, the simplest stable logic is:
    // "Any time range NOT covered by a Segment (or explicit Kept Range) is skipped?"
    // No, we want to skip only what was DELETED via Ripple.

    // Let's rely on the `sourceStart`/`sourceEnd` vs `start`/`end` diff.
    // S1: start 0, end 5. sourceStart 0, sourceEnd 5.
    // [User deletes S2 (5-10)] -> Ripple happens.
    // S3 (was 10-15): newStart 5, newEnd 10. sourceStart 10, sourceEnd 15.

    // Detecting the jump:
    // Between S1.end (5) and S3.newStart (5):
    // Diff in Source: S3.sourceStart (10) - S1.sourceEnd (5) = 5.
    // Diff in Virtual: S3.newStart (5) - S1.end (5) = 0.
    // Source Gap (5) > Virtual Gap (0) => We must SKIP 5 seconds of source.

    // General Logic:
    // Iterate segments.
    // For the segment itself: It's a linear play.
    // For the gap *before* the segment (between Prev.end and Curr.start):
    // Check source gap (Curr.sourceStart - Prev.sourceEnd).
    // Check virtual gap (Curr.start - Prev.end).
    // If SourceGap > VirtualGap, we have a "Cut".
    // Skip = SourceGap - VirtualGap.

    let lastVirtualEnd = 0;
    let lastSourceEnd = 0;

    // Start from 0
    if (sorted.length > 0) {
      lastSourceEnd = sorted[0].sourceStart - sorted[0].start; // Offset? No.
      // Assume video starts at 0 source and 0 virtual for simplicity unless first seg moved.
      // Actually, let's just trace.
      lastVirtualEnd = 0;
      lastSourceEnd = 0;
    }

    for (const s of sorted) {
      // Gap Handling
      const virGap = s.start - lastVirtualEnd;
      // Source Gap? We don't know exactly where source "was" for the gap unless we assume linearity from previous sourceEnd.
      // But wait, the GAP in Virtual Timeline should map to GAP in Source.
      // If we didn't cut the gap, then SourceGap == VirGap.
      // If we cut the gap, well... we usually cut Segments.
      //
      // Let's look at the Segments themselves. They are the anchors.
      // Map Entry: { vStart, vEnd, sStart, sEnd }

      map.push({
        vStart: s.start,
        vEnd: s.end,
        sStart: s.sourceStart ?? s.start,
        sEnd: s.sourceEnd ?? s.end
      });

      // What about the gap BEFORE this segment?
      // If s.start > lastVirtualEnd, there is a Virtual Gap.
      // We assume this gap maps to Source Gap of same length immediately preceding s.sourceStart?
      // Or immediately following lastSourceEnd?
      // This is ambiguous if we cut *within* a gap.
      // But our tool only deletes *Segments*.
      // So the "Gap" between segments is preserved relative to the segments?
      // Actually, if we ripple delete, we shift S3 to S1.
      // The gap between S1 and S3 *disappears* if S2 was covering it?
      //
      // ROBUST APPROACH:
      // We only play "Segments".
      // Gaps between segments are... Silence.
      // In "Timeline" view, Silence is just time passing.
      // Does the Source Video jump during silence?
      // If I delete S2, S3 moves to touch S1. Gap is gone.
      // So we just play S1, then jump to S3.
      // What if there is a deliberate silence gap I want to keep?
      // If I didn't delete it, it exists in Virtual.
      //
      // Let's assume:
      // 1. We play the segments.
      // 2. Any gap between segments in Virtual Timeline is "Silence" that maps linearly to Source.
      //    (i.e. Source Gap = Virtual Gap)
      //    BUT, anchor it to the *Previous* segment's end or *Next* segment's start?
      //    Let's anchor to Previous Segment End.

      if (s.start > lastVirtualEnd) {
        // There is a gap.
        // Map it linearly from lastSourceEnd.
        map.push({
          vStart: lastVirtualEnd,
          vEnd: s.start,
          sStart: lastSourceEnd,
          sEnd: lastSourceEnd + (s.start - lastVirtualEnd)
        });
      }

      lastVirtualEnd = s.end;
      lastSourceEnd = s.sourceEnd ?? s.end;
    }

    // Sort map by vStart just in case
    map.sort((a, b) => a.vStart - b.vStart);

    // Calculate total virtual duration
    const duration = map.length > 0 ? map[map.length - 1].vEnd : 0;

    return { map, duration };
  };

  useEffect(() => {
    // Recalculate map whenever segments change
    const { map, duration } = calculateTimeMap(segments);
    setTimeMap(map);
    setVirtualDuration(duration);
  }, [segments]);

  // Convert Source Time (from video player) to Virtual Time (for UI)
  const sourceToVirtual = (sTime) => {
    // Find which segment this source time belongs to
    // This is tricky because multiple source ranges might overlap if we did crazy edits, 
    // but with ripple delete, source ranges are unique.
    // However, we might have skipped parts.
    // We want to find the entry in the map where sStart <= sTime <= sEnd.
    const entry = timeMap.find(m => sTime >= m.sStart - 0.1 && sTime <= m.sEnd + 0.1);
    if (entry) {
      const offset = sTime - entry.sStart;
      return entry.vStart + offset;
    }
    // If not in map (skipped part), we map to the END of the previous valid part?
    // Or simply return closest?
    return -1; // Fallback (Prevent jumping to 0)
  };

  // Convert Virtual Time (UI/Seek) to Source Time (Video Player)
  const virtualToSource = (vTime) => {
    const entry = timeMap.find(m => vTime >= m.vStart && vTime <= m.vEnd);
    if (entry) {
      const offset = vTime - entry.vStart;
      return entry.sStart + offset;
    }
    // If beyond end?
    return 0;
  };


  const saveToHistory = () => {
    // History saves everything including source times
    setHistory([...history, JSON.stringify(segments)]);
  };

  const undo = () => {
    if (history.length === 0) return;
    const previous = history[history.length - 1];
    setSegments(JSON.parse(previous));
    setHistory(history.slice(0, -1));
  };

  const updateSegment = (index, field, value) => {
    saveToHistory();
    const newSegments = [...segments];
    // Use loose equality for numbers/strings match
    const val = field === 'text' ? value : parseFloat(value);
    newSegments[index][field] = val;

    // For Phase 2: If manual timing edit happens, we update sourceTime to match 
    // timeline time, UNLESS it's a ripple shift. But here it's manual.
    // Simplifying assumption: Manual edit resets source sync for that point.
    if (field === 'start') newSegments[index].sourceStart = val;
    if (field === 'end') newSegments[index].sourceEnd = val;

    setSegments(newSegments);
  };

  const deleteSegment = (index) => {
    const msg = cutMode
      ? "【重要】動画の該当箇所をカット（削除）して、後ろを詰めますか？\n※動画の尺が短くなります。"
      : "この字幕を削除してもよろしいですか？";

    if (window.confirm(msg)) {
      saveToHistory();
      const s = segments[index];
      const duration = s.end - s.start;

      const newSegments = [...segments];
      newSegments.splice(index, 1);

      if (cutMode) {
        // Ripple Delete: Shift all subsequent segments left
        for (let i = index; i < newSegments.length; i++) {
          newSegments[i].start = parseFloat((newSegments[i].start - duration).toFixed(3));
          newSegments[i].end = parseFloat((newSegments[i].end - duration).toFixed(3));
          // sourceStart/sourceEnd UNCHANGED (they refer to original video)
        }
      }
      setSegments(newSegments);
    }
  };

  const mergeSegments = (index) => {
    if (index >= segments.length - 1) return;
    saveToHistory();
    const current = segments[index];
    const next = segments[index + 1];

    // Merge: New source range is Union(s1, s2). 
    const newSourceEnd = next.sourceEnd;

    // Combine
    const newSegment = {
      ...current,
      text: current.text + " " + next.text,
      end: next.end,
      sourceEnd: newSourceEnd
    };

    const newSegments = [...segments];
    newSegments.splice(index, 2, newSegment);
    setSegments(newSegments);
  };

  // 再帰的な分割ロジック (SourceTime対応版)
  const recursiveSplit = (text, start, end, sourceStart, sourceEnd, depth = 0) => {
    // 終了条件
    if (text.length <= 25 || depth > 5) {
      return [{ text, start, end, sourceStart, sourceEnd }];
    }

    // 分割ロジック (既存)
    const center = text.length / 2;
    let bestSplitIndex = -1;
    let minScore = Infinity;

    const findBestIn = (regex, weight) => {
      let m;
      let loopCount = 0;
      regex.lastIndex = 0;
      while ((m = regex.exec(text)) !== null) {
        loopCount++;
        if (loopCount > 1000) break;
        const pos = m.index + m[0].length;
        if (pos === 0 || pos >= text.length) continue;
        const score = Math.abs(pos - center) * weight;
        if (score < minScore) {
          minScore = score;
          bestSplitIndex = pos;
        }
      }
    };
    findBestIn(/[、。！？]/g, 1.0);
    findBestIn(/(って|て|で)/g, 1.0);
    if (bestSplitIndex === -1 || minScore > center * 1.5) {
      findBestIn(/(は|が|を|に|へ|と|も|の)/g, 3.0);
    }

    if (bestSplitIndex === -1) {
      return [{ text, start, end, sourceStart, sourceEnd }];
    }

    // Split Execution
    let t1 = text.substring(0, bestSplitIndex).replace('|', '').trim();
    let t2 = text.substring(bestSplitIndex).replace('|', '').trim();

    const duration = end - start;
    const ratio = bestSplitIndex / text.length;
    const midTime = start + (duration * ratio);

    // Calculate mid Source Time
    // Handle undefined source times by falling back to timeline times
    const sStart = sourceStart ?? start;
    const sEnd = sourceEnd ?? end;
    const sourceDuration = sEnd - sStart;
    const midSource = sStart + (sourceDuration * ratio);

    const leftParts = recursiveSplit(t1, start, parseFloat(midTime.toFixed(3)), sStart, parseFloat(midSource.toFixed(3)), depth + 1);
    const rightParts = recursiveSplit(t2, parseFloat(midTime.toFixed(3)), end, parseFloat(midSource.toFixed(3)), sEnd, depth + 1);

    return [...leftParts, ...rightParts];
  };

  const smartSplit = (index) => {
    saveToHistory();
    const s = segments[index];

    // 1. 手動 '|' があればそこで切る (最優先、再帰なし)
    if (s.text.indexOf('|') !== -1) {
      const splitPos = s.text.indexOf('|');
      let t1 = s.text.substring(0, splitPos).trim();
      let t2 = s.text.substring(splitPos + 1).trim();
      const duration = s.end - s.start;
      const ratio = splitPos / s.text.length;
      const midTime = s.start + (duration * ratio);
      const midSource = (s.sourceStart ?? s.start) + ((s.sourceEnd ?? s.end) - (s.sourceStart ?? s.start)) * ratio;

      const newSegments = [...segments];
      newSegments[index] = { ...s, text: t1, end: parseFloat(midTime.toFixed(2)), sourceEnd: parseFloat(midSource.toFixed(2)) };
      newSegments.splice(index + 1, 0, {
        start: parseFloat(midTime.toFixed(2)),
        end: s.end,
        text: t2,
        sourceStart: parseFloat(midSource.toFixed(2)),
        sourceEnd: s.sourceEnd ?? s.end
      });
      setSegments(newSegments);
      return;
    }

    // 2. 再帰的自動分割
    const newParts = recursiveSplit(s.text, s.start, s.end, s.sourceStart ?? s.start, s.sourceEnd ?? s.end);

    // 現在のセグメントを、分割された複数のセグメントで置き換える
    const newSegments = [...segments];
    newSegments.splice(index, 1, ...newParts);
    setSegments(newSegments);
  };

  const handleRemoveSpaces = () => {
    const fixedSegments = segments.map(s => {
      // Logic: Remove spaces between Japanese characters (Non-ASCII to Non-ASCII)
      // Example: "出会 った" -> "出会った"
      // Preserves: "Hello World"
      const newText = s.text.replace(/([^\x01-\x7E])\s+([^\x01-\x7E])/g, '$1$2');
      return { ...s, text: newText };
    });

    // Check if any changes occurred
    const changedCount = fixedSegments.filter((s, i) => s.text !== segments[i].text).length;

    if (changedCount === 0) {
      alert("✨ 修正が必要な空白は見つかりませんでした。");
    } else {
      setSegments(fixedSegments);
      alert(`✨ ${changedCount}箇所の不要な空白を削除しました！`);
    }
  };

  // --- AI Rhythm Master Logic ---
  const getSegmentWarning = (text) => {
    if (!text) return '';
    const len = text.length;
    if (len > targetChars + 5) return 'warning-long';
    if (len > 0 && len < 3) return 'warning-short';
    return '';
  };

  const handleSegmentKeyDown = (e, index) => {
    if (e.ctrlKey && e.key === 'Enter') {
      e.preventDefault();
      const textarea = e.target;
      const cursor = textarea.selectionStart;
      const text = segments[index].text;

      const part1 = text.substring(0, cursor);
      const part2 = text.substring(cursor);

      if (!part1 || !part2) return; // Don't split empty

      // Create new segment for part2
      const currentSeg = segments[index];

      // Calculate split time (approximate based on char ratio)
      const totalDuration = currentSeg.end - currentSeg.start;
      const splitRatio = part1.length / text.length;
      const splitTime = currentSeg.start + (totalDuration * splitRatio);

      // --- FIX: Calculate Source Time for accurate seeking ---
      const sStart = currentSeg.sourceStart ?? currentSeg.start;
      const sEnd = currentSeg.sourceEnd ?? currentSeg.end;
      const splitSource = sStart + ((sEnd - sStart) * splitRatio);

      const newSeg1 = {
        ...currentSeg,
        text: part1,
        end: Number(splitTime.toFixed(2)),
        sourceEnd: Number(splitSource.toFixed(2))
      };

      const newSeg2 = {
        ...currentSeg,
        text: part2,
        start: Number(splitTime.toFixed(2)),
        sourceStart: Number(splitSource.toFixed(2)),
        id: Date.now()
      };

      const newSegments = [...segments];
      newSegments.splice(index, 1, newSeg1, newSeg2);
      setSegments(newSegments);

      // Auto-focus new segment (next tick)
      setTimeout(() => {
        const nextEl = document.getElementById(`segment-${index + 1}`);
        if (nextEl) {
          const ta = nextEl.querySelector('textarea');
          if (ta) ta.focus();
        }
      }, 50);
    }
  };

  const analyzeAndFixRhythm = async () => {
    // 1. Find LONG segments
    const anomalies = segments.map((s, i) => ({ ...s, index: i })).filter(s => s.text.length > targetChars + 5);

    if (anomalies.length === 0) {
      alert("✨ すべてのリズムは最適です！");
      return;
    }

    if (!confirm(`${anomalies.length}箇所の読みづらい字幕が見つかりました。\nAIで一括最適化しますか？`)) return;

    let newSegments = [...segments];
    let offset = 0; // Index shift due to splits

    for (const anomaly of anomalies) {
      const currentIndex = anomaly.index + offset;
      const currentSeg = newSegments[currentIndex];

      try {
        const res = await apiFetch('postRhythmSplit', { body: { text: currentSeg.text, target_chars: targetChars } });
        const data = await res.json();
        const parts = data.parts || [currentSeg.text];

        if (parts.length > 1) {
          // Apply Split
          const totalDur = currentSeg.end - currentSeg.start;
          const totalLen = currentSeg.text.length;
          let currentTime = currentSeg.start;

          // --- FIX: Source Time Base ---
          let currentSource = currentSeg.sourceStart ?? currentSeg.start;
          const totalSourceDur = (currentSeg.sourceEnd ?? currentSeg.end) - currentSource;

          const splitSegs = parts.map((part, pIdx) => {
            const ratio = part.length / totalLen;
            const duration = totalDur * ratio;
            const sourceDuration = totalSourceDur * ratio;

            const seg = {
              ...currentSeg,
              text: part,
              start: Number(currentTime.toFixed(2)),
              end: Number((currentTime + duration).toFixed(2)),
              sourceStart: Number(currentSource.toFixed(2)),
              sourceEnd: Number((currentSource + sourceDuration).toFixed(2)),
              id: currentSeg.id + `_${pIdx}` // Unique ID
            };
            currentTime += duration;
            currentSource += sourceDuration;
            return seg;
          });

          // Replace 1 with N
          newSegments.splice(currentIndex, 1, ...splitSegs);
          offset += (splitSegs.length - 1);
        }
      } catch (err) {
        console.error("Split failed", err);
      }
    }

    setSegments(newSegments);
    alert("✨ 最適化が完了しました！");
  };


  const handleTimeUpdate = () => {
    if (!videoRef.current) return;
    const sTime = videoRef.current.currentTime;

    // Check if current source time is valid in our map
    // If we are in a "deleted" zone, we should jump to next valid.
    // However, floating point issues... let's check if we are "in a gap".

    // Simple check: Convert Source -> Virtual. 
    // If returns 0 (fallback) and sTime > 0.5, we might be lost?
    // Better: Find the exact map entry.

    // Logic:
    // If sTime is > entry.sEnd and < nextEntry.sStart => we are in a Cut Gap.
    // Jump to nextEntry.sStart.

    // OPTIMIZATION: Only check if playing.
    if (!videoRef.current.paused) {
      // Find if we are inside any valid range
      const validRange = timeMap.find(m => sTime >= m.sStart - 0.1 && sTime < m.sEnd);
      // Note: use < sEnd to allow hitting the end boundary

      if (!validRange) {
        // We are not in a valid range. We are likely in a gap.
        // Find the NEXT valid range.
        // sorted map by sStart
        const sortedMap = [...timeMap].sort((a, b) => a.sStart - b.sStart);
        const nextRange = sortedMap.find(m => m.sStart > sTime);

        if (nextRange) {
          console.log(`Skipping driven by TimeMap: ${sTime.toFixed(2)} -> ${nextRange.sStart.toFixed(2)} `);
          videoRef.current.currentTime = nextRange.sStart + 0.01; // nudge
          return;
        }
      }
    }

    // Update UI Time (Virtual)
    const vTime = sourceToVirtual(sTime);
    setCurrentTime(vTime);

    const index = segments.findIndex(s => vTime >= s.start && vTime < s.end);
    if (index !== activeSegmentIndex) {
      setActiveSegmentIndex(index);
      if (index !== -1) {
        const card = document.getElementById(`segment - ${index} `);
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }

    // Smart Focus Loop (Phase 11)
    if (isLoopMode && index !== -1 && !videoRef.current.paused) {
      const seg = segments[index];
      if (vTime >= seg.end - 0.1) {
        videoRef.current.currentTime = virtualToSource(seg.start);
      }
    }
  };

  const handleReplaceAll = () => {
    if (!searchText) return;
    saveToHistory();
    let count = 0;
    const newSegments = segments.map(s => {
      if (s.text.includes(searchText)) {
        const occurrences = s.text.split(searchText).length - 1;
        count += occurrences;
        return { ...s, text: s.text.replaceAll(searchText, replaceText) };
      }
      return s;
    });
    setSegments(newSegments);
    alert(`${count}箇所の "${searchText}" を "${replaceText}" に置換しました。`);
    setShowSearch(false);
  };


  const handleSave = async () => {
    console.log("[App] handleSave called. State:", { scenes, audioConfig });
    setIsRendering(true); // Reuse loading state for spinner
    try {
      // 1. Save Segments
      await apiFetch('postSegments', { body: segments });

      // 2. Save Director State (Scenes & Audio)
      await apiFetch('postDirectorState', { body: { scenes, audioConfig } });

      alert("保存しました！ (字幕 + 演出構成)");
    } catch (e) {
      console.error(e);
      alert("保存に失敗しました。");
    } finally {
      setIsRendering(false);
    }
  };

  const handleRender = async () => {
    setIsVerifying(true);
    try {
      // 1. Join segments for full text analysis
      const fullText = segments.map(s => s.text).join('\n');

      // 2. Call Quality Gate API
      const res = await apiFetch('postDirectorVerifyQuality', { body: {
          full_text: fullText,
          scenes: scenes,
          segments: segments
        } });
      const data = await res.json();
      setQualityGateData(data);
      setShowQualityGate(true);
    } catch (e) {
      console.error(e);
      alert("品質検査に失敗しました。");
    } finally {
      setIsVerifying(false);
    }
  };

  const executeRealRender = async () => {
    setShowQualityGate(false);
    setIsRendering(true);
    try {
      const res = await apiFetch('postRender', { body: {
          mode: cutMode ? "cut" : "normal",
          style: subtitleStyle
        } });
      const data = await res.json();
      if (data.status === "success") {
        alert("動画が正常に書き出されました！\n場所: " + data.path);
      } else {
        alert("エラーが発生しました: " + data.detail);
      }
    } catch (e) {
      alert("通信エラーが発生しました。");
    } finally {
      setIsRendering(false);
    }
  };

  const setTimestampAtCurrent = (index, field) => {
    saveToHistory();
    // User sees Virtual Time. We set Virtual Time.
    // UI logic uses updateSegment which sets Timeline Time.
    // Timeline Time IS Virtual Time.
    updateSegment(index, field, currentTime.toFixed(1));
  };







  // Scene History for Undo/Redo
  const [sceneHistory, setSceneHistory] = useState([]);

  const saveSceneHistory = useCallback(() => {
    // Current scenes are strictly copied to history
    setSceneHistory(prev => [...prev, JSON.stringify(scenes)]);
  }, [scenes]);

  const undoScene = useCallback(() => {
    if (sceneHistory.length === 0) return;
    const previous = JSON.parse(sceneHistory[sceneHistory.length - 1]);
    setScenes(previous);
    setSceneHistory(prev => prev.slice(0, -1));
  }, [sceneHistory]);

  const handleApplyTemplate = (newScenes, audio) => {
    console.log("[App] handleApplyTemplate called", { newScenes, audio });
    if (scenes.length > 0) saveSceneHistory(); // Save before overwrite
    setScenes(newScenes);
    setAudioConfig(audio);
    alert(`AIディレクター: ${newScenes.length} 個のシーン構成を適用しました！\nBGM: ${audio ? audio.name : 'なし'} \nプレビューに追加します。`);
    setEditMode('director');
  };

  const handleUpdateScene = (index, updatedScene) => {
    saveSceneHistory(); // Save before update
    const newScenes = [...scenes];
    newScenes[index] = updatedScene;
    setScenes(newScenes);
  };

  const handleUpdateAllScenes = (newScenes) => {
    saveSceneHistory(); // Save before update
    setScenes(newScenes);
  };

  return (
    <>
    <div className="app-container" onMouseMove={resize} onMouseUp={stopResizing} onMouseLeave={stopResizing}>
      {/* Boardroom is now a view, not an overlay */}

      {/* Global Status Bar */}
      {isRendering && (
        <div className="global-status-bar" style={{
          position: 'fixed', bottom: '20px', left: '50%', transform: 'translateX(-50%)',
          background: 'rgba(16, 185, 129, 0.95)', color: 'white', padding: '12px 25px',
          borderRadius: '50px', boxShadow: '0 5px 20px rgba(0,0,0,0.4)', zIndex: 3000,
          display: 'flex', alignItems: 'center', gap: '12px', fontWeight: 'bold',
          backdropFilter: 'blur(5px)', border: '1px solid rgba(255,255,255,0.2)'
        }}>
          <Loader size={20} className="spinning" />
          <span>動画書き出し中... (このまま他の作業を行えます)</span>
        </div>
      )}

      {/* P0-2: 初回オンボーディング */}
      {showOnboarding && (
        <WelcomeOnboarding onComplete={() => setShowOnboarding(false)} />
      )}

      {/* AI Director Wizard */}
      <DirectorWizard
        isOpen={showWizard}
        onClose={() => setShowWizard(false)}
        onApplyTemplate={handleApplyTemplate}
      />

      {/* Header — Phase 1: みらい議会風「1画面1メッセージ」 */}
      <header className="app-header" style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: '56px',
        background: 'rgba(255,255,255,0.92)', backdropFilter: 'blur(12px)',
        borderBottom: '1px solid rgba(0,0,0,0.06)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '0 24px', zIndex: 100,
      }}>
        <div className="header-left" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <h1 style={{
            fontSize: '1.1rem', margin: 0, fontWeight: 800,
            background: 'linear-gradient(135deg, #7C3AED, #EC4899)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            letterSpacing: '-0.02em',
          }}>Antigravity</h1>
        </div>
        <div className="header-right" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {/* CTA: 制作開始 */}
          <button onClick={() => setShowPipeline(true)} style={{
            background: pipelineRunning
              ? 'linear-gradient(135deg, #10b981, #059669)'
              : 'linear-gradient(135deg, #7C3AED, #6D28D9)',
            border: 'none', color: 'white', borderRadius: '10px',
            padding: '8px 20px', fontWeight: 700, cursor: 'pointer',
            fontFamily: 'Noto Sans JP', fontSize: '0.88rem',
            boxShadow: pipelineRunning
              ? '0 2px 12px rgba(16,185,129,0.3)'
              : '0 2px 12px rgba(124,58,237,0.25)',
            transition: 'all 0.2s ease',
            animation: pipelineRunning ? 'pulse-glow 2s ease-in-out infinite' : 'none',
          }}>
            {pipelineRunning ? `⏳ ${pipelineStageName || '処理中'}...` : '▶ 制作する'}
          </button>

          {/* ツールメニュー */}
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setShowToolMenu(!showToolMenu)}
              style={{
                background: showToolMenu ? '#f3f0ff' : 'transparent',
                border: '1px solid rgba(0,0,0,0.08)',
                color: '#64748B', borderRadius: '10px',
                padding: '8px 16px', fontWeight: 600, cursor: 'pointer',
                fontFamily: 'Noto Sans JP', fontSize: '0.85rem',
                transition: 'all 0.2s ease',
              }}
            >
              ⚙ ツール {showToolMenu ? '▴' : '▾'}
            </button>
            {showToolMenu && (
              <div style={{
                position: 'absolute', top: '44px', right: 0,
                background: 'white', borderRadius: '12px',
                border: '1px solid rgba(0,0,0,0.06)',
                boxShadow: '0 8px 30px rgba(0,0,0,0.12)',
                padding: '6px', minWidth: '200px', zIndex: 200,
                animation: 'fadeSlideDown 0.15s ease',
              }}>
                {[
                  { icon: '⚙', label: '設定', action: () => { setView(view === 'settings' ? 'editor' : 'settings'); setShowToolMenu(false); }, active: view === 'settings' },
                  { icon: '🛡️', label: '戦略会議室', action: () => { setView('boardroom'); setShowToolMenu(false); }, active: view === 'boardroom' },
                  { icon: '🎨', label: 'テーマ選択', action: () => { setShowThemeSelector(true); setShowToolMenu(false); } },
                  { icon: '⚡', label: 'クイックレビュー', action: () => {
                    setQuickDecisionItems(suggestions.map(s => ({
                      id: s.id, title: s.message, context: s.context || '', type: s.type,
                    })));
                    setShowQuickDecision(true); setShowToolMenu(false);
                  }},
                  { icon: '✅', label: '最終確認', action: () => {
                    setStepReviewData({
                      segments: segments, scenes: scenes,
                      qualityScore: qualityGateData?.score || null,
                    });
                    setShowStepReview(true); setShowToolMenu(false);
                  }},
                ].map((item, i) => (
                  <button key={i} onClick={item.action} style={{
                    display: 'flex', alignItems: 'center', gap: '10px',
                    width: '100%', padding: '10px 14px', border: 'none',
                    background: item.active ? '#f3f0ff' : 'transparent',
                    borderRadius: '8px', cursor: 'pointer', textAlign: 'left',
                    fontFamily: 'Noto Sans JP', fontSize: '0.88rem',
                    color: item.active ? '#7C3AED' : '#334155',
                    fontWeight: item.active ? 700 : 500,
                    transition: 'all 0.15s ease',
                  }}
                  onMouseEnter={e => e.target.style.background = '#f8fafc'}
                  onMouseLeave={e => e.target.style.background = item.active ? '#f3f0ff' : 'transparent'}
                  >
                    <span style={{ fontSize: '1.1rem' }}>{item.icon}</span>
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 保存ボタン */}
          <button onClick={handleSave} style={{
            background: 'transparent', border: '1px solid rgba(0,0,0,0.08)',
            color: '#64748B', borderRadius: '10px',
            padding: '8px 14px', fontWeight: 600, cursor: 'pointer',
            fontFamily: 'Noto Sans JP', fontSize: '0.85rem',
            transition: 'all 0.2s ease',
          }}>
            💾
          </button>
        </div>
      </header>

      <div className="main-content" style={{ marginTop: '50px', height: 'calc(100vh - 50px)', display: 'flex', overflow: 'hidden' }}>

        {view === 'settings' ? (
          <div style={{ width: '100%', overflowY: 'auto' }}>
            <SettingsPage onClose={() => setView('editor')} />
          </div>
        ) : view === 'boardroom' ? (
          <div style={{ width: '100%', overflowY: 'auto' }}>
            <Boardroom onClose={() => setView('editor')} />
          </div>
        ) : (
          <div className="fade-in" style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
            {/* AI Partner Overlay - might need to be outside if absolute, but it's usually fixed/absolute. Let's keep it inside. */}

            {/* AI Partner Overlay */}


            {/* 左パネル: プレビュー */}
            <div className="preview-pane">
              <div className="video-wrapper">
                <video
                  ref={videoRef}
                  src={apiUrl('getVideo', { query: { t: videoTimestamp } })}
                  controls
                  onTimeUpdate={handleTimeUpdate}
                  style={{ opacity: (scenes.length > 0 && showDirectorOverlay) ? 0 : 1 }}
                />

                {scenes.length > 0 && (
                  <button
                    onClick={() => setShowDirectorOverlay(!showDirectorOverlay)}
                    style={{
                      position: 'absolute', top: '10px', right: '10px', zIndex: 100,
                      padding: '5px 10px', borderRadius: '20px', fontSize: '0.8rem',
                      background: 'rgba(0,0,0,0.5)', color: '#fff', border: '1px solid rgba(255,255,255,0.3)', cursor: 'pointer'
                    }}
                  >
                    {showDirectorOverlay ? '👁️ 元動画を見る' : '🎨 演出を見る'}
                  </button>
                )}

                {/* AI Director Preview Overlay */}
                {scenes.length > 0 && showDirectorOverlay && (
                  <div className="director-preview-overlay">
                    {(() => {
                      // Simple calculation to find active scene based on progress
                      // Assuming 10min total for now, or distributed equally. 
                      // Mock: Distribute scenes across 60 seconds for demo visualization
                      const sceneDuration = 60 / scenes.length;
                      const currentSceneIdx = Math.min(
                        Math.floor(currentTime / sceneDuration),
                        scenes.length - 1
                      );
                      const activeScene = scenes[currentSceneIdx];

                      if (!activeScene) return null;

                      return (
                        <>
                          {/* Background Image */}
                          <div className="preview-bg-image" style={{ backgroundImage: `url(${activeScene.image || '/assets/samples/sample_talk.png'})` }}></div>

                          {/* BGM Info (Subtle) */}
                          {audioConfig && (
                            <div className="preview-bgm-indicator">
                              🎵 {audioConfig.name} ({audioConfig.style})
                            </div>
                          )}

                          {/* Nanobanana Style Telop */}
                          <div className="nanobanana-telop-container">
                            <div className="telop-decoration">✨</div>
                            <h2 className="telop-main-text">{activeScene.name}</h2>
                            <p className="telop-sub-text">{activeScene.description}</p>
                          </div>
                        </>
                      );
                    })()}
                  </div>
                )}

                {/* Live Style Preview Overlay */}
                {scenes.length === 0 && activeSegmentIndex !== -1 && segments[activeSegmentIndex] && (
                  <div className="subtitle-overlay-container" style={{ transform: `translateY(${subtitleY}px)` }}>
                    <div className={`subtitle-text style-${subtitleStyle === 'youtuber' ? 'tiktok' :
                      subtitleStyle === 'cinematic' ? 'cinema' :
                        subtitleStyle === 'cute' ? 'cute' : 'standard'
                      }`}
                      style={{ transform: `scale(${subtitleScale})`, transformOrigin: 'bottom center' }}
                    >
                      {segments[activeSegmentIndex].text}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Resizer Handle */}
            <div
              className={`resizer ${isResizing ? 'active' : ''} `}
              onMouseDown={startResizing}
            />



            {/* Center Panel: Subtitle List / Timeline */}
            <div className="center-pane" style={{ flex: 1, overflowY: 'auto', position: 'relative', background: '#f8fafc' }}>

              {editMode === 'director' ? (
                <SceneTimeline
                  scenes={scenes}
                  audioConfig={audioConfig}
                  segments={segments} // Pass full subtitle data for AI Context
                  onUpdateScene={handleUpdateScene}
                  onUpdateAllScenes={handleUpdateAllScenes}
                  onUndo={undoScene}
                  canUndo={sceneHistory.length > 0}
                  onOpenBoardroom={(query) => {
                    setBoardroomQuery(query);
                    setShowBoardroom(true);
                  }}
                />
              ) : (
                <>
                  {/* Boardroom Overlay */}
                  {showBoardroom && (
                    <Boardroom
                      onClose={() => {
                        setShowBoardroom(false);
                        setBoardroomQuery(""); // Clear query on close
                      }}
                      initialQuery={boardroomQuery}
                    />
                  )}

                  {/* Soul Passport Overlay */}
                  {showSoulPassport && (
                    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 3000, background: '#fff' }}>
                      <SoulPassport onClose={() => setShowSoulPassport(false)} />
                    </div>
                  )}

                  {/* Collaborative Studio Overlay */}
                  <CollaborativePanel
                    isOpen={showCollaborativePanel}
                    onClose={() => setShowCollaborativePanel(false)}
                    currentRole={currentRole}
                    onRoleChange={setCurrentRole}
                  />

                  {/* Quality Gate Overlay */}
                  <QualityGate
                    isOpen={showQualityGate}
                    onClose={() => setShowQualityGate(false)}
                    onConfirm={executeRealRender}
                    data={qualityGateData}
                  />

                  {/* Search Dialog (Absolute) */}
                  {showSearch && (
                    <div className="search-dialog fade-in" style={{
                      position: 'sticky', top: '10px', left: '10px', right: '10px',
                      background: '#fff', border: '1px solid #ccc', borderRadius: '12px',
                      padding: '1.5rem', boxShadow: '0 10px 30px rgba(0,0,0,0.15)', zIndex: 200, margin: '10px'
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1.5rem', alignItems: 'center' }}>
                        <h3 style={{ margin: 0, fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <Search size={18} /> 検索と置換
                        </h3>
                        <button onClick={() => setShowSearch(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '5px', borderRadius: '50%' }}>
                          <X size={18} color="#666" />
                        </button>
                      </div>
                      <div style={{ marginBottom: '1rem' }}>
                        <label style={{ display: 'block', fontSize: '0.85rem', color: '#666', marginBottom: '5px' }}>検索する文字</label>
                        <input type="text" value={searchText} onChange={e => setSearchText(e.target.value)} style={{ width: '100%', padding: '10px', borderRadius: '6px', border: '1px solid #ddd', fontSize: '1rem' }} placeholder="例: 私" autoFocus />
                      </div>
                      <div style={{ marginBottom: '1.5rem' }}>
                        <label style={{ display: 'block', fontSize: '0.85rem', color: '#666', marginBottom: '5px' }}>置換後の文字</label>
                        <input type="text" value={replaceText} onChange={e => setReplaceText(e.target.value)} style={{ width: '100%', padding: '10px', borderRadius: '6px', border: '1px solid #ddd', fontSize: '1rem' }} placeholder="例: 僕" />
                      </div>
                      <button className="btn-primary" style={{ width: '100%', padding: '12px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px' }} onClick={handleReplaceAll}>
                        すべて置換を実行
                      </button>
                    </div>
                  )}

                  <div className="segments-list" ref={listRef} style={{ padding: '20px', paddingBottom: '100px' }}>
                    {segments.map((s, i) => (
                      <div
                        key={i}
                        id={`segment-${i}`}
                        className={`segment-card ${i === activeSegmentIndex ? 'active' : ''} ${getSegmentWarning(s.text)}`}
                        onClick={() => jumpToSegment(i)}
                      >
                        <div className="card-header">
                          <div className="time-inputs">
                            <input type="number" step="0.1" value={s.start} onChange={(e) => updateSegment(i, 'start', e.target.value)} />
                            <span>→</span>
                            <input type="number" step="0.1" value={s.end} onChange={(e) => updateSegment(i, 'end', e.target.value)} />
                          </div>
                          <div className="quick-set">
                            <button className="btn-secondary" onClick={() => setTimestampAtCurrent(i, 'start')}>開始</button>
                            <button className="btn-secondary" onClick={() => setTimestampAtCurrent(i, 'end')}>終了</button>
                            <button className={`btn-secondary ${cutMode ? 'btn-danger' : 'btn-danger'}`} style={cutMode ? { border: '2px solid red', fontWeight: 'bold' } : {}} onClick={() => deleteSegment(i)}>
                              {cutMode ? "削除(詰める)" : "削除"}
                            </button>
                          </div>
                        </div>
                        <textarea
                          value={s.text}
                          rows={2}
                          onChange={(e) => updateSegment(i, 'text', e.target.value)}
                          onKeyDown={(e) => handleSegmentKeyDown(e, i)}
                          className={s.text.includes('\n') ? 'multiline' : ''}
                        />
                        <div className="card-footer">
                          {i < segments.length - 1 && (
                            <button className="btn-link" onClick={() => mergeSegments(i)}>▼ 下の行と結合する</button>
                          )}
                        </div>
                        {(s.text.length > 20 || s.text.includes('|')) && (
                          <div className="ai-suggest">
                            <div className="suggest-text">💡 {s.text.includes('|') ? 'マーカー位置で分割します' : '字幕が長いです。AI分割を試しますか？'}</div>
                            <button className="btn-link" onClick={() => smartSplit(i)}>➤ AIに任せて分割する</button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>

            {/* Right Panel: Command Center (Visual Cockpit) */}
            <div className="command-center" style={{ width: '360px', minWidth: '360px', background: '#f8fafc', borderLeft: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column', height: '100%' }}>

              {/* 1. Primary Navigation (Tabs) */}
              <div className="footer-tabs" style={{ background: 'transparent', padding: '0 0 10px 0', border: 'none', minHeight: 'auto', marginTop: 0 }}>
                <button className={`tab-btn ${editMode === 'subtitle' ? 'active' : ''}`} onClick={() => setEditMode('subtitle')} style={{ flex: 1, justifyContent: 'center', borderRadius: '12px', marginRight: '5px' }}>📝 字幕</button>
                <button className={`tab-btn ${editMode === 'director' ? 'active' : ''}`} onClick={() => setEditMode('director')} style={{ flex: 1, justifyContent: 'center', borderRadius: '12px' }}>🎬 演出</button>
              </div>

              {/* 2. Project Card (Common) */}
              <div className="command-card project-card">
                <div className="card-title">🎥 プロジェクト情報</div>
                <div className="project-info">
                  <span className="project-name">新しいプロジェクト</span>
                  <span className="version-badge">第1稿</span>
                </div>
                <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <button className="btn-secondary" onClick={() => setShowSoulPassport(true)} style={{ width: '100%', justifyContent: 'center', background: '#6366f1', color: '#fff', border: 'none' }}>
                    📖 成長記録
                  </button>
                  <button className="btn-secondary" onClick={() => setShowCollaborativePanel(true)} style={{ width: '100%', justifyContent: 'center', background: '#0071e3', color: '#fff', border: 'none' }}>
                    🤝 二人三脚スタジオ
                  </button>
                </div>
              </div>

              {/* 3. Publishing Card (Common) */}
              <div className="command-card publishing-card">
                <div className="card-title">🚀 パブリッシング</div>
                <div className="publish-grid">
                  <button className="btn-primary" onClick={handleSave} style={{ width: '100%', justifyContent: 'center', padding: '10px' }}>
                    💾 保存
                  </button>
                  <button className="btn-secondary" onClick={handleRender} disabled={isRendering || isVerifying} style={{ width: '100%', justifyContent: 'center', padding: '10px' }}>
                    {isVerifying ? "品質検査中..." : (isRendering ? "処理中..." : "🎬 書き出し")}
                  </button>
                </div>
                {/* Mock Auto-save status */}
                <div className="save-status">最終保存: 2分前</div>
              </div>

              {editMode === 'subtitle' && (
                <>
                  {/* 4. Style Card (Visual Selector) */}
                  <div className="command-card style-card">
                    <div className="card-title">🎨 デザイン＆スタイル</div>
                    <div className="visual-style-grid">
                      <div className={`style-tile ${subtitleStyle === 'default' ? 'active' : ''}`} onClick={() => setSubtitleStyle('default')}>
                        <span className="tile-icon">🏳️</span>
                        <span className="tile-label">標準</span>
                      </div>
                      <div className={`style-tile ${subtitleStyle === 'youtuber' ? 'active' : ''}`} onClick={() => setSubtitleStyle('youtuber')}>
                        <span className="tile-icon">✨</span>
                        <span className="tile-label">YouTuber</span>
                      </div>
                      <div className={`style-tile ${subtitleStyle === 'cinematic' ? 'active' : ''}`} onClick={() => setSubtitleStyle('cinematic')}>
                        <span className="tile-icon">🎬</span>
                        <span className="tile-label">映画風</span>
                      </div>
                      <div className={`style-tile ${subtitleStyle === 'cute' ? 'active' : ''}`} onClick={() => setSubtitleStyle('cute')}>
                        <span className="tile-icon">🍑</span>
                        <span className="tile-label">かわいい</span>
                      </div>
                    </div>
                    {/* Position & Size Controls */}
                    <div style={{ marginTop: '15px', padding: '10px', background: '#f1f5f9', borderRadius: '8px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      {/* Position */}
                      <div style={{ display: 'flex', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.8rem', marginRight: '10px', color: '#64748b', width: '60px' }}>↕️ 位置</span>
                        <input
                          type="range" min="-200" max="200" step="10"
                          value={subtitleY} onChange={(e) => setSubtitleY(Number(e.target.value))}
                          style={{ flex: 1, cursor: 'grab' }}
                        />
                      </div>
                      {/* Size */}
                      <div style={{ display: 'flex', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.8rem', marginRight: '10px', color: '#64748b', width: '60px' }}>🔠 サイズ</span>
                        <input
                          type="range" min="0.5" max="2.0" step="0.1"
                          value={subtitleScale} onChange={(e) => setSubtitleScale(Number(e.target.value))}
                          style={{ flex: 1, cursor: 'grab' }}
                        />
                        <span style={{ fontSize: '0.7rem', marginLeft: '5px', color: '#666', width: '30px' }}>{subtitleScale}x</span>
                      </div>
                    </div>
                  </div>

                  {/* 5. Toolkit Card */}
                  <div className="command-card toolkit-card">
                    <div className="card-title">🛠 ツールキット</div>

                    {/* Rhythm Control */}
                    <div style={{ background: '#f8fafc', padding: '10px', borderRadius: '8px', marginBottom: '10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.8rem', fontWeight: 'bold', color: '#4a5568' }}>🎶 AIリズム</span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                          <input
                            type="number"
                            value={targetChars}
                            onChange={(e) => setTargetChars(Number(e.target.value))}
                            style={{ width: '40px', padding: '2px', border: '1px solid #ccc', borderRadius: '4px', textAlign: 'center' }}
                          />
                          <span style={{ fontSize: '0.7rem', color: '#666' }}>文字/行</span>
                        </div>
                      </div>
                      <button className="btn-primary" style={{ fontSize: '0.8rem', justifyContent: 'center' }} onClick={analyzeAndFixRhythm}>
                        ✨ 一括リズム調整 (AI)
                      </button>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
                      <button className="btn-secondary btn-toolkit" onClick={handleRemoveSpaces}>
                        🧹 空白削除
                      </button>
                      <button className="btn-secondary btn-toolkit" onClick={() => setShowSearch(!showSearch)}>
                        🔍 検索
                      </button>
                      <button className="btn-secondary btn-toolkit" style={{ gridColumn: '1 / -1' }} onClick={() => setShowWizard(true)}>
                        ✨ AI構成ウィザード
                      </button>
                    </div>
                    {/* Switches */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#4a5568', padding: '0 5px' }}>
                      <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}>
                        <input type="checkbox" checked={cutMode} onChange={() => setCutMode(!cutMode)} style={{ marginRight: '6px' }} />
                        ✂️ 動画カット
                      </label>
                      <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}>
                        <input type="checkbox" checked={isLoopMode} onChange={() => setIsLoopMode(!isLoopMode)} style={{ marginRight: '6px' }} />
                        🔄 ループ
                      </label>
                    </div>
                  </div>
                </>
              )}

              {/* 6. AI Partner (Filling remaining space) */}
              <AIAssistant
                suggestions={suggestions}
                onAction={handleSuggestionAction}
                onDismiss={dismissSuggestion}
              />
            </div>

          </div>
        )}
      </div>
      {/* Shortcut Guide Overlay */}
      {
        showShortcuts && (
          <div className="shortcut-overlay fade-in" style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.6)', zIndex: 9999,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            backdropFilter: 'blur(3px)'
          }} onClick={() => setShowShortcuts(false)}>
            <div className="shortcut-card" style={{
              background: '#fff', borderRadius: '16px', padding: '2rem', width: '600px',
              boxShadow: '0 20px 50px rgba(0,0,0,0.3)', pointerEvents: 'auto', position: 'relative'
            }} onClick={e => e.stopPropagation()}>
              <h2 style={{ marginTop: 0, borderBottom: '1px solid #eee', paddingBottom: '10px' }}>⌨️ キーボードショートカット</h2>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginTop: '20px' }}>
                <div>
                  <h4 style={{ color: '#666', borderLeft: '3px solid #3b82f6', paddingLeft: '10px' }}>基本操作</h4>
                  <ul style={{ listStyle: 'none', padding: 0 }}>
                    <li style={{ marginBottom: '15px', display: 'flex', justifyContent: 'space-between' }}><span>再生 / 一時停止</span> <kbd style={{ background: '#f3f4f6', padding: '2px 8px', borderRadius: '6px', border: '1px solid #d1d5db', fontWeight: 'bold' }}>Space</kbd></li>
                    <li style={{ marginBottom: '15px', display: 'flex', justifyContent: 'space-between' }}><span>閉じる</span> <kbd style={{ background: '#f3f4f6', padding: '2px 8px', borderRadius: '6px', border: '1px solid #d1d5db', fontWeight: 'bold' }}>Esc</kbd></li>
                    <li style={{ marginBottom: '15px', display: 'flex', justifyContent: 'space-between' }}><span>ショートカット一覧</span> <kbd style={{ background: '#f3f4f6', padding: '2px 8px', borderRadius: '6px', border: '1px solid #d1d5db', fontWeight: 'bold' }}>?</kbd></li>
                  </ul>
                </div>
                <div>
                  <h4 style={{ color: '#666', borderLeft: '3px solid #8b5cf6', paddingLeft: '10px' }}>AIエディター</h4>
                  <ul style={{ listStyle: 'none', padding: 0 }}>
                    <li style={{ marginBottom: '15px', display: 'flex', justifyContent: 'space-between' }}><span>取り消し (Undo)</span> <span><kbd style={{ background: '#f3f4f6', padding: '2px 8px', borderRadius: '6px', border: '1px solid #d1d5db', fontWeight: 'bold' }}>Ctrl</kbd> + <kbd style={{ background: '#f3f4f6', padding: '2px 8px', borderRadius: '6px', border: '1px solid #d1d5db', fontWeight: 'bold' }}>Z</kbd></span></li>
                  </ul>
                </div>
              </div>
              <div style={{ marginTop: '2rem', textAlign: 'right' }}>
                <button className="btn-primary" onClick={() => setShowShortcuts(false)}>閉じる</button>
              </div>
            </div>
          </div>
        )
      }
    </div >

    {/* Production Pipeline Modal */}
    {showPipeline && (
      <ProductionPipeline
        onClose={() => setShowPipeline(false)}
        onWizardStart={(pipelineResult) => {
          setShowPipeline(false);
          // **`|| 0` で未計測を 0 点に潰さない**（R1.5-C4・13周目の指摘）。
          // `ProductionWizard` 側は 9周目（7f8198a）に「未計測」の枝を入れたが、
          // **点を注入しているこの呼び出し元が直っていなかった**ので、
          // その枝には本番から到達できなかった（9・10周目と同じ「門が
          // 本番から到達不能」の型）。
          //
          // `||` は 0 を falsy として弾くので、実測 0 点まで握り潰す。
          // `??` にしたうえで、**旗も一緒に渡す**（0 は実際に取りうる点なので
          // 値だけでは未計測と区別できない）。
          setWizardContext({
            segments: segments,
            quality_score: pipelineResult?.quality_details?.score
              ?? pipelineResult?.quality_score
              ?? null,
            quality_scored: pipelineResult?.quality_details?.scored
              ?? pipelineResult?.quality_scored
              ?? false,
            quality_feedback: pipelineResult?.quality_details?.feedback || [],
            category_report: pipelineResult?.quality_details?.category_report || [],
            metadata: pipelineResult?.metadata || {},
          });
          setShowProductionWizard(true);
        }}
      />
    )}

    {/* ━━━ R-4: ThemeSelector Modal ━━━ */}
    {showThemeSelector && (
      <ThemeSelector
        isOpen={showThemeSelector}
        onClose={() => setShowThemeSelector(false)}
        segments={segments}
        onApply={(config) => {
          console.log('🎨 テンプレート適用:', config);
          setShowThemeSelector(false);
        }}
      />
    )}

    {/* ━━━ R-2: QuickDecision Modal ━━━ */}
    {showQuickDecision && (
      <QuickDecisionBar
        items={quickDecisionItems}
        onDecisionComplete={(results) => {
          console.log('✅ クイックレビュー完了:', results);
          setShowQuickDecision(false);
        }}
        onClose={() => setShowQuickDecision(false)}
      />
    )}

    {/* ━━━ R-3: StepReview Modal ━━━ */}
    {showStepReview && (
      <StepReviewPanel
        isOpen={showStepReview}
        onClose={() => setShowStepReview(false)}
        reviewData={stepReviewData}
        onApprove={() => {
          console.log('✅ 段階的レビュー承認');
          setShowStepReview(false);
        }}
      />
    )}

    {/* ━━━ D-1: Production Wizard ━━━ */}
    {showProductionWizard && wizardContext && (
      <ProductionWizard
        isOpen={showProductionWizard}
        onClose={() => setShowProductionWizard(false)}
        context={wizardContext}
        onRender={async () => {
          setShowProductionWizard(false);
          try {
            const res = await apiFetch('postRender', { body: { mode: 'normal', style: 'default' } });
            const data = await res.json();
            console.log('🎬 レンダリング完了:', data);
            // パイプラインの最終出力パスがある場合、ダウンロード案内
            if (wizardContext.metadata?.final_path) {
              alert(`✅ レンダリング完了！\n出力先: ${wizardContext.metadata.final_path}`);
            } else {
              alert('✅ レンダリングを開始しました。');
            }
          } catch (err) {
            console.error('Render API error:', err);
            alert('レンダリングAPI呼び出しに失敗しました。手動で書き出しを行ってください。');
          }
        }}
      />
    )}
    </>
  );
}
