
// App.jsxから修正後のロジックを抜粋して再現 (Standard Match Version)

const text = "先生ラジオをやってらっしゃっていろんな医療のお話をされているんで";
const center = text.length / 2;
let bestSplitIndex = -1;
let minScore = Infinity;

function findBestIn(regex, weight) {
    let m;
    let loopCount = 0;
    regex.lastIndex = 0;
    while ((m = regex.exec(text)) !== null) {
        loopCount++;
        if (loopCount > 1000) break;

        // Normal Match: m.index is start. POS should be AFTER the match.
        const pos = m.index + m[0].length;

        if (pos === 0 || pos >= text.length) continue;

        const score = Math.abs(pos - center) * weight;

        console.log(`Match at ${pos} ("${text.substring(Math.max(0, pos - 5), pos)}"|"${text.substring(pos, Math.min(text.length, pos + 5))}"). Score: ${score.toFixed(2)} [Regex: ${regex}]`);

        if (score < minScore) {
            minScore = score;
            bestSplitIndex = pos;
        }
    }
}

console.log("Original Text:", text);
console.log("Center:", center);

// A. 句読点 (、。！？) (weight 1.0)
findBestIn(/[、。！？]/g, 1.0);

// B. 接続語 (って, て, で) (weight 1.0)
findBestIn(/(って|て|で)/g, 1.0);

// C. 弱い助詞 (weight 3.0)
if (bestSplitIndex === -1 || minScore > center * 1.5) {
    findBestIn(/(は|が|を|に|へ|と|も|の)/g, 3.0);
}

console.log("Best Split Index:", bestSplitIndex);

if (bestSplitIndex !== -1) {
    let t1 = text.substring(0, bestSplitIndex).trim();
    let t2 = text.substring(bestSplitIndex).trim();
    console.log("Result 1:", t1);
    console.log("Result 2:", t2);

    if (t1.endsWith("やってらっしゃって")) {
        console.log("SUCCESS: Correctly split after 'やってらっしゃって'");
    } else {
        console.log("FAILURE: Split at " + bestSplitIndex + " ('" + t1.slice(-5) + "')");
    }
} else {
    console.log("FAILURE: No split found");
}
