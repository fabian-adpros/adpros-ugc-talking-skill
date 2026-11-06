import React from 'react';
import {Composition} from 'remotion';
import {TalkingHead} from './TalkingHead';
import type {TalkingHeadProps} from './types';

const defaultProps: TalkingHeadProps = {
  videoSrc: 'placeholder.mp4',
  musicSrc: null,
  musicVolume: 0.1259,
  durationInSeconds: 1,
  highlight: true,
  hook: {text: 'Hook', start: 0, end: 3},
  captions: [
    {
      start: 0.1,
      end: 0.9,
      words: [
        {text: 'Bold', start: 0.1, end: 0.45},
        {text: 'captions', start: 0.45, end: 0.9},
      ],
    },
  ],
  style: {
    fontFamily: 'Inter',
    captionSize: 72,
    hookSize: 62,
    color: '#FFFFFF',
    highlightColor: '#FFE14A',
    captionY: 0.46,
    hookY: 0.16,
    safe: {top: 250, bottom: 420, left: 80, right: 140},
  },
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="TalkingHead"
      component={TalkingHead}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={30}
      defaultProps={defaultProps}
      calculateMetadata={({props}) => {
        const fps = 30;
        const seconds = Math.max(0.5, props.durationInSeconds || 1);
        return {
          durationInFrames: Math.max(1, Math.ceil(seconds * fps)),
          fps,
          width: 1080,
          height: 1920,
          props,
        };
      }}
    />
  );
};
