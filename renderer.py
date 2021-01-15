#!/usr/bin/env python3

import argparse
import sys
import os
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

from PIL import Image

from mpeg2ts.packet import Packet
from mpeg2ts.section import Section
from mpeg2ts.parser import SectionParser, PESParser
from mpeg2ts.mjd import BCD, MJD_to_YMD
from subtitle.render import Renderer

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=('ARIB subtitle renderer'))

  parser.add_argument('-i', '--input', type=argparse.FileType('rb'), nargs='?', default=sys.stdin.buffer)
  parser.add_argument('-o', '--output_path', type=Path, nargs='?', default=Path(os.getcwd()))
  # parser.add_argument('-o', '--output', type=str, nargs='?', default=".")
  parser.add_argument('-s', '--SID', type=int, nargs='?')
  parser.add_argument('-f', '--ffmpeg', action='store_true')
  #parser.add_argument('-p', '--PES', action='store_true', help='テスト用')
  # parser.add_argument('-v', '--verbose', dest='v', action='store_true')

  args = parser.parse_args()
  os.makedirs(args.output_path, exist_ok=True)

  PAT_Parser = SectionParser()
  PMT_Parser = SectionParser()
  TOT_Parser = SectionParser()
  SUBTITLE_Parser = PESParser()

  PMT_PID = -1
  PCR_PID = -1
  SUBTITLE_PID = -1

  FIRST_PCR = None
  FIRST_TOT = None

  while args.input:
    while True:
      sync_byte = args.input.read(1)
      if not sync_byte: sys.exit()
      if sync_byte == Packet.SYNC_BYTE: break

    packet = Packet.SYNC_BYTE + args.input.read(Packet.PACKET_SIZE - 1)
    ts = Packet(packet)

    if ts.pid() == 0x00:
      PAT_Parser.push(ts)
      while not PAT_Parser.empty():
        PAT = PAT_Parser.pop()
        if PAT.CRC32() != 0: continue

        begin = Section.HEADER_SIZE
        while begin < 3 + PAT.section_length() - Section.CRC_SIZE:
          program_number = (PAT[begin + 0] << 8) | PAT[begin + 1]
          program_map_PID = ((PAT[begin + 2] & 0x1F) << 8) | PAT[begin + 3]

          if program_number == args.SID:
            PMT_PID = program_map_PID

          begin += 4
    elif ts.pid() == PMT_PID:
      PMT_Parser.push(ts)
      while not PMT_Parser.empty():
        PMT = PMT_Parser.pop()
        if PMT.CRC32() != 0: continue

        PCR_PID = ((PMT[Section.HEADER_SIZE + 0] & 0x1F) << 8) | PMT[Section.HEADER_SIZE + 1]
        program_info_length = ((PMT[Section.HEADER_SIZE + 2] & 0x0F) << 8) | PMT[Section.HEADER_SIZE + 3]

        begin = Section.HEADER_SIZE + 4 + program_info_length
        while begin < 3 + PMT.section_length() - Section.CRC_SIZE:
          stream_type = PMT[begin + 0]
          elementary_PID = ((PMT[begin + 1] & 0x1F) << 8) | PMT[begin + 2]
          ES_info_length = ((PMT[begin + 3] & 0x0F) << 8) | PMT[begin + 4]

          descriptor = begin + 5
          while descriptor < (begin + 5 + ES_info_length):
            descriptor_tag = PMT[descriptor + 0]
            descriptor_length = PMT[descriptor + 1]
            if descriptor_tag == 0x52:
              component_tag = PMT[descriptor + 2]
              if stream_type == 0x06 and component_tag == 0x30: # Aプロファイルの字幕のデフォルトESが 0x30  (ARIB TR-B14 2 4.2.8.1 コンポーネントタグの運用)
                SUBTITLE_PID = elementary_PID
            descriptor += 2 + descriptor_length

          begin += 5 + ES_info_length
    elif ts.pid() == PCR_PID:
      if not FIRST_TOT:
        FIRST_PCR = ts.pcr()
    elif ts.pid() == 0x14:
      TOT_Parser.push(ts)
      while not TOT_Parser.empty():
        TOT = TOT_Parser.pop()
        if TOT.CRC32() != 0: continue
        if FIRST_TOT: continue
        if not FIRST_PCR: continue

        MJD = (TOT[3 + 0] << 8) + TOT[3 + 1]
        year, month, day = MJD_to_YMD(MJD)
        hour = BCD(TOT[3 + 2])
        min = BCD(TOT[3 + 3])
        sec = BCD(TOT[3 + 4])

        FIRST_TOT = datetime(year, month, day, hour, min, sec)

    elif ts.pid() == SUBTITLE_PID:
      SUBTITLE_Parser.push(ts)
      while not SUBTITLE_Parser.empty():
        SUBTITLE = SUBTITLE_Parser.pop()
        if not FIRST_TOT: continue

        renderer = Renderer(SUBTITLE)
        renderer.render()
        if renderer.fgImage:
          image = Image.new('RGBA', renderer.swf)
          image.alpha_composite(renderer.bgImage)
          image.alpha_composite(renderer.fgImage)

          elapsed_seconds = timedelta(seconds = (((1 << 33) - 1) + (renderer.PTS() - FIRST_PCR)) % ((1 << 33) - 1) / 90000)
          renderer_time = FIRST_TOT + elapsed_seconds

          renderer_time_str = renderer_time.strftime('%Y%m%d%H%M%S%f')
          output_path = args.output_path.joinpath('{}.png'.format(renderer_time_str))
          if args.ffmpeg:
            output_ffmpeg_path = args.output_path.joinpath('{}-ffmpeg.png'.format(renderer_time_str))
            ffmpeg = subprocess.Popen([
             'ffmpeg',
             '-ss', str(elapsed_seconds.total_seconds()),
             '-i', args.input.name,
             '-frames:v', '1',
             '-s', '1920x1080',
             output_ffmpeg_path,
            ])
            ffmpeg.wait()

            ffmpeg_image = Image.open(output_ffmpeg_path)
            ffmpeg_image.putalpha(255)
            ffmpeg_image.alpha_composite(image.resize((ffmpeg_image.width, ffmpeg_image.height)))
            ffmpeg_image.save(output_path)
            os.remove(output_ffmpeg_path)
          else:
            image.save(output_path)

