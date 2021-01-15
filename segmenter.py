#!/usr/bin/env python3

import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

from mpeg2ts.packet import Packet
from mpeg2ts.section import Section
from mpeg2ts.parser import SectionParser
from mpeg2ts.mjd import BCD, MJD_to_YMD

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=('ARIB mpeg2ts segmenter'))

  parser.add_argument('-i', '--input', type=argparse.FileType('rb'), nargs='?', default=sys.stdin.buffer)
  parser.add_argument('-o', '--output_path', type=Path, nargs='?', default=Path(os.getcwd()))
  parser.add_argument('-s', '--SID', type=int, required=True)

  args = parser.parse_args()
  os.makedirs(args.output_path, exist_ok=True)

  EIT_Parser = SectionParser()
  current = None
  segment = None

  while args.input:
    while True:
      sync_byte = args.input.read(1)
      if not sync_byte: sys.exit()
      if sync_byte == Packet.SYNC_BYTE: break

    packet = Packet.SYNC_BYTE + args.input.read(Packet.PACKET_SIZE - 1)
    ts = Packet(packet)

    if ts.pid() == 0x12:
      EIT_Parser.push(ts)
      while not EIT_Parser.empty():
        EIT = EIT_Parser.pop()
        if EIT.CRC32() != 0: continue
        if EIT.table_id() != 0x4e: continue
        if EIT.section_number() != 0: continue
        if EIT.table_id_extension() != args.SID: continue

        MJD = (EIT[Section.HEADER_SIZE + 6 + 2 + 0] << 8) + EIT[Section.HEADER_SIZE + 6 + 2 + 1]
        year, month, day = MJD_to_YMD(MJD)
        hour = BCD(EIT[Section.HEADER_SIZE + 6 + 2 + 2])
        min = BCD(EIT[Section.HEADER_SIZE + 6 + 2 + 3])
        sec = BCD(EIT[Section.HEADER_SIZE + 6 + 2 + 4])
        starttime = datetime(year, month, day, hour, min, sec)
        if starttime != current:
          current = starttime
          if segment: segment.close()
          path = args.output_path.joinpath(starttime.strftime('%Y%m%d%H%M%S.ts'))
          os.makedirs(path.parent, exist_ok=True)
          segment = open(path, 'wb')

      if segment: segment.write(packet)
    else:
      if segment: segment.write(packet)

  if segment: segment.close()
