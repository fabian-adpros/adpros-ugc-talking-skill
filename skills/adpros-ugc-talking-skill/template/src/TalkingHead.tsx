import React, {useEffect, useState} from 'react';
import {
  AbsoluteFill,
  Audio,
  continueRender,
  delayRender,
  interpolate,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import type {CaptionCard, TalkingHeadProps} from './types';

const activeCard = (captions: CaptionCard[], time: number): CaptionCard | null => {
  return captions.find((card) => time >= card.start && time < card.end + 0.02) ?? null;
};

export const TalkingHead: React.FC<TalkingHeadProps> = (props) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  const time = frame / fps;
  const [fontHandle] = useState(() => delayRender('Loading Inter'));
  useEffect(() => {
    const face = new FontFace('Inter', `url(${staticFile('fonts/Inter-Bold.ttf')})`, {
      weight: '700',
    });
    let settled = false;
    const done = () => {
      if (settled) {
        return;
      }
      settled = true;
      continueRender(fontHandle);
    };
    face
      .load()
      .then((loaded) => {
        document.fonts.add(loaded);
        done();
      })
      .catch(() => done());
  }, [fontHandle]);

  const safe = props.style.safe;
  const card = activeCard(props.captions ?? [], time);
  const hook = props.hook;
  const hookEnd = hook?.end ?? 3;
  const hookOpacity =
    hook && time <= hookEnd
      ? interpolate(time, [hookEnd - 0.35, hookEnd], [1, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        })
      : 0;

  return (
    <AbsoluteFill style={{backgroundColor: '#141820', fontFamily: 'Inter, sans-serif'}}>
      <OffthreadVideo src={staticFile(props.videoSrc)} />
      {props.musicSrc ? (
        <Audio src={staticFile(props.musicSrc)} volume={props.musicVolume} />
      ) : null}
      {hook && hookOpacity > 0.01 ? (
        <div
          style={{
            position: 'absolute',
            top: Math.max(safe.top, height * props.style.hookY),
            left: safe.left,
            right: safe.right,
            transform: 'translateY(0)',
            display: 'flex',
            justifyContent: 'center',
            opacity: hookOpacity,
          }}
        >
          <div
            style={{
              background: 'rgba(0,0,0,0.55)',
              color: '#fff',
              fontWeight: 700,
              fontSize: props.style.hookSize,
              lineHeight: 1.12,
              textAlign: 'center',
              whiteSpace: 'pre-wrap',
              padding: '14px 22px',
              borderRadius: 18,
              maxWidth: '100%',
              textShadow: '0 2px 0 rgba(0,0,0,0.45)',
            }}
          >
            {hook.text}
          </div>
        </div>
      ) : null}
      {card ? (
        <div
          style={{
            position: 'absolute',
            top: height * props.style.captionY,
            left: safe.left,
            right: safe.right,
            transform: 'translateY(-50%)',
            display: 'flex',
            justifyContent: 'center',
            gap: 14,
            flexWrap: 'wrap',
          }}
        >
          {card.words.map((word, index) => {
            const active = props.highlight && time >= word.start && time < word.end + 0.04;
            return (
              <span
                key={`${word.start}-${index}`}
                style={{
                  color: active ? props.style.highlightColor : props.style.color,
                  fontWeight: 700,
                  fontSize: props.style.captionSize,
                  lineHeight: 1.05,
                  WebkitTextStroke: '8px #000',
                  paintOrder: 'stroke fill',
                  textShadow: '0 3px 0 rgba(0,0,0,0.35)',
                }}
              >
                {word.text}
              </span>
            );
          })}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
