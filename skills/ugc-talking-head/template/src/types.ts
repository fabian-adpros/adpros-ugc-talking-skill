export type CaptionWord = {
  text: string;
  start: number;
  end: number;
};

export type CaptionCard = {
  start: number;
  end: number;
  words: CaptionWord[];
};

export type Hook = {
  text: string;
  start: number;
  end: number;
  alternates?: string[];
  reason?: string;
};

export type SafeZone = {
  top: number;
  bottom: number;
  left: number;
  right: number;
};

export type TalkingHeadProps = {
  videoSrc: string;
  musicSrc: string | null;
  musicVolume: number;
  durationInSeconds: number;
  highlight: boolean;
  hook: Hook | null;
  captions: CaptionCard[];
  style: {
    fontFamily: string;
    captionSize: number;
    hookSize: number;
    color: string;
    highlightColor: string;
    captionY: number;
    hookY: number;
    safe: SafeZone;
  };
};
