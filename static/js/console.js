/**
 * @module console Console web component widget.
 */
import { Widget } from "/static/js/widget.js";
import { clip } from "/static/js/math.js";


/** batlowK color map */
const COLOR_MAP = [
    "#020305", "#030507", "#04070a", "#05090c", "#060b0f", "#070d11",
    "#080f12", "#091014", "#0a1216", "#0b1317", "#0c1419", "#0d161a",
    "#0e171c", "#0f181d", "#0f191f", "#101b21", "#101c22", "#111d24",
    "#111f26", "#122027", "#122129", "#12232b", "#13242c", "#14262e",
    "#142730", "#152831", "#152a33", "#162b35", "#172d36", "#172e38",
    "#183039", "#19313b", "#1a333c", "#1a343e", "#1b363f", "#1c3740",
    "#1d3842", "#1e3a43", "#1f3b44", "#203d46", "#213e47", "#223f48",
    "#234149", "#24424a", "#25434b", "#26454b", "#27464c", "#28474d",
    "#2a484e", "#2b494e", "#2c4b4f", "#2d4c4f", "#2e4d50", "#2f4e50",
    "#304f50", "#315051", "#335151", "#345251", "#355251", "#365351",
    "#375451", "#385551", "#395651", "#3a5751", "#3b5751", "#3c5851",
    "#3e5950", "#3f5950", "#405a50", "#415b50", "#425b4f", "#435c4f",
    "#445d4f", "#455d4e", "#465e4e", "#475f4d", "#485f4d", "#4a604d",
    "#4b604c", "#4c614c", "#4d614b", "#4e624b", "#4f634a", "#50634a",
    "#516449", "#536448", "#546548", "#556647", "#566647", "#576746",
    "#586746", "#5a6845", "#5b6844", "#5c6944", "#5d6a43", "#5f6a43",
    "#606b42", "#616b41", "#626c41", "#646d40", "#656d40", "#666e3f",
    "#686f3e", "#696f3e", "#6a703d", "#6c703d", "#6d713c", "#6f723b",
    "#70723b", "#71733a", "#73743a", "#747439", "#767539", "#777638",
    "#797637", "#7a7737", "#7c7836", "#7d7836", "#7f7935", "#817a35",
    "#827a35", "#847b34", "#857c34", "#877c33", "#897d33", "#8b7e33",
    "#8c7e32", "#8e7f32", "#907f32", "#918032", "#938132", "#958131",
    "#978231", "#998331", "#9a8331", "#9c8431", "#9e8532", "#a08532",
    "#a28632", "#a48632", "#a68732", "#a78833", "#a98833", "#ab8934",
    "#ad8934", "#af8a35", "#b18a35", "#b38b36", "#b58c37", "#b68c38",
    "#b88d38", "#ba8d39", "#bc8e3a", "#be8e3b", "#c08f3c", "#c18f3d",
    "#c3903e", "#c59040", "#c79041", "#c89142", "#ca9143", "#cc9245",
    "#ce9246", "#cf9347", "#d19349", "#d3944a", "#d4944c", "#d6954d",
    "#d7954f", "#d99550", "#da9652", "#dc9654", "#dd9756", "#df9757",
    "#e09859", "#e1985b", "#e3995d", "#e4995e", "#e59a60", "#e69a62",
    "#e89b64", "#e99b66", "#ea9c68", "#eb9c6a", "#ec9d6c", "#ed9e6e",
    "#ee9e70", "#ef9f72", "#f09f74", "#f1a076", "#f2a178", "#f2a17a",
    "#f3a27c", "#f4a27e", "#f5a380", "#f5a482", "#f6a484", "#f6a587",
    "#f7a589", "#f8a68b", "#f8a78d", "#f8a78f", "#f9a891", "#f9a993",
    "#faa995", "#faaa97", "#faab99", "#fbab9b", "#fbac9d", "#fbad9f",
    "#fbada1", "#fbaea3", "#fcaea5", "#fcafa7", "#fcb0a8", "#fcb0aa",
    "#fcb1ac", "#fcb2ae", "#fcb2b0", "#fcb3b2", "#fcb4b4", "#fdb4b6",
    "#fdb5b8", "#fdb6ba", "#fdb6bc", "#fdb7bd", "#fdb8bf", "#fdb8c1",
    "#fdb9c3", "#fdb9c5", "#fdbac7", "#fdbbc9", "#fdbbcb", "#fcbccd",
    "#fcbdcf", "#fcbdd1", "#fcbed3", "#fcbfd5", "#fcc0d7", "#fcc0d9",
    "#fcc1db", "#fcc2dd", "#fcc2df", "#fcc3e1", "#fcc4e3", "#fbc4e5",
    "#fbc5e7", "#fbc6e9", "#fbc7eb", "#fbc7ed", "#fbc8ef", "#fbc9f1",
    "#fac9f4", "#facaf6", "#facbf8", "#faccfa",
];

/** Maximum log level. */
const MAX_LOG_LEVEL = 50;


/**
 * Get batlowK hex color value string for some alpha in [0, 1].
 */
function get_color(alpha) {
    const beta = clip(alpha, 0, 1);
    let idx = parseInt( beta * (COLOR_MAP.length - 1) );
    return COLOR_MAP[idx];
}


function time() {
    return Date.now() / 1000;
}


class Console extends Widget {
    constructor(maxlen=50) {
        super();
        this.maxlen = maxlen;

        this._append_link("static/css/console.css");
        this.list = document.createElement("ul");
        this.shadowRoot.appendChild(this.list);
        this.blockedUntil = -Infinity;
    }

    connectedCallback() {
        this.addEventListener("mouseover", () => {
            this.blockedUntil = Infinity;
        });
        this.addEventListener("mouseleave", () => {
            this.blockedUntil = time() + 2;
        });
    }

    get auto_scrolling() {
        const now = time();
        return now >= this.blockedUntil;
    }


    /**
     * Remove oldest log entry from list.
     */
    remove_oldest() {
        this.list.removeChild(this.list.childNodes[0]);
    }

    /**
     * Scroll to bottom.
     */
    scroll_all_the_way_down() {
        this.list.scrollTop = this.list.scrollHeight;
    }

    /**
     * Process new log record.
     */
    new_log_messages(record) {
        while (this.list.childNodes.length > this.maxlen) {
            this.remove_oldest();
        }

        const li = document.createElement("li");
        this.list.appendChild(li);
        li.innerHTML = record.name + "<i> " + record.message.replaceAll("\n", "<br>") + "</i>";
        li.style.color = get_color(record.level / MAX_LOG_LEVEL);

        if (this.auto_scrolling)
            this.scroll_all_the_way_down();
    }
}

customElements.define("being-console", Console);
