#!/usr/bin/env python3

import argparse
import sys

from mpeg2ts.packet import Packet
from mpeg2ts.section import Section
from mpeg2ts.parser import SectionParser

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=('ARIB mpeg2ts splitter'))

  parser.add_argument('-i', '--input', type=argparse.FileType('rb'), nargs='?', default=sys.stdin.buffer)
  parser.add_argument('-o', '--output', type=argparse.FileType('wb'), nargs='?', default=sys.stdout.buffer)
  parser.add_argument('-s', '--SID', type=int, required=True)
  parser.add_argument('-p', '--PID', type=int, nargs='*')

  args = parser.parse_args()

  PAT_Parser = SectionParser()
  PAT_Continuity_Counter = 0

  PMT_Parser = SectionParser()

  PMT_PID = -1
  SID_PIDS = []

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

        modified = Section(PAT[0:Section.HEADER_SIZE])

        begin = Section.HEADER_SIZE
        while begin < 3 + PAT.section_length() - Section.CRC_SIZE:
          program_number = (PAT[begin + 0] << 8) | PAT[begin + 1]
          program_map_PID = ((PAT[begin + 2] & 0x1F) << 8) | PAT[begin + 3]

          if program_number == args.SID:
            PMT_PID = program_map_PID
            modified += PAT[begin:begin+4]

          begin += 4
        section_length = len(modified) + Section.CRC_SIZE - 3
        modified[1] = (modified[1] & 0xF0) & ((section_length & 0x0F00) >> 8)
        modified[2] = (section_length & 0xFF)
        modified += modified.CRC32().to_bytes(Section.CRC_SIZE, byteorder="big")

        begin = 0
        while begin < 3 + modified.section_length():
          header  = ts[0].to_bytes(1, byteorder="big")
          header += ((ts[1] & 0xBF) | ((1 if begin == 0 else 0) << 6)).to_bytes(1, byteorder="big")
          header += ts[2].to_bytes(1, byteorder="big")
          header += ((ts[3] & 0xF0) | (PAT_Continuity_Counter & 0x0F)).to_bytes(1, byteorder="big")
          PAT_Continuity_Counter += 1
          PAT_Continuity_Counter &= 0x0F;

          next = min(3 + PAT.section_length(), begin + (Packet.PACKET_SIZE - Packet.HEADER_SIZE) - (1 if begin == 0 else 0))
          payload = (b'\x00' if begin == 0 else b'') + modified[begin:next]
          payload += Packet.STUFFING_BYTE * max(0, Packet.PACKET_SIZE - (Packet.HEADER_SIZE + len(payload)))
          args.output.write(header + payload)

          begin = next

    elif ts.pid() == PMT_PID:
      PMT_Parser.push(ts)
      while not PMT_Parser.empty():
        PMT = PMT_Parser.pop()
        if PMT.CRC32() != 0: continue

        PCR_PID = ((PMT[Section.HEADER_SIZE + 0] & 0x1F) << 8) | PMT[Section.HEADER_SIZE + 1]
        program_info_length = ((PMT[Section.HEADER_SIZE + 2] & 0x0F) << 8) | PMT[Section.HEADER_SIZE + 3]

        SID_PIDS.clear()
        SID_PIDS.append(PCR_PID)

        begin = Section.HEADER_SIZE + 4 + program_info_length
        while begin < 3 + PMT.section_length() - Section.CRC_SIZE:
          stream_type = PMT[begin + 0]
          elementary_PID = ((PMT[begin + 1] & 0x1F) << 8) | PMT[begin + 2]
          ES_info_length = ((PMT[begin + 3] & 0x0F) << 8) | PMT[begin + 4]
          SID_PIDS.append(elementary_PID)
          begin += 5 + ES_info_length

      args.output.write(packet)
    elif ts.pid() in SID_PIDS:
      args.output.write(packet)
    elif args.PID and ts.pid() in args.PID:
      args.output.write(packet)
