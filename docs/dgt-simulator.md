# DGT e-board simulator

`tools/dgt_simulator.py` lets you test PicoChess with an e-board without the
hardware. It creates a virtual serial port that speaks the DGT protocol, so
PicoChess runs its real DGT driver: connection, lifting and placing pieces,
`set pieces`, takeback on the board, Scan, and engine moves that have to be
made on the board.

It works on Linux and macOS (it needs a pseudo-terminal). Windows is not
supported.

## Start

```bash
venv/bin/python tools/dgt_simulator.py
```

The simulator prints its serial port (`/tmp/dgt-sim` by default) and opens a
web page on <http://localhost:8081>.

Point PicoChess at it, either in the setup wizard (`/setup`, choose *DGT
e-board*, port *Other port…* `/tmp/dgt-sim`, *Test connection*, *Save*) or in
`picochess.ini`:

```ini
board-type = dgt
dgt-port = /tmp/dgt-sim
```

Then (re)start PicoChess. The simulator page shows *PicoChess connected* and the
PicoChess footer shows *DGT*.

## Use

- Click a piece to lift it, then click a square to put it down. PicoChess
  receives every lift and every placement, as with a real board. Lifting a piece
  and putting it back on the same square is the usual DGT gesture for hints and
  window switching.
- *Make a move* (`e2e4`, `e7e8q`) performs a whole move the way a person would:
  captured piece first, castling rook and en passant included.
- When the engine has moved, the simulator highlights the move and offers
  *Make this move on the board*. It learns the move from PicoChess's web events,
  like the LEDs of a board.
- *Copy PicoChess position* makes the board match PicoChess, for example after
  a New Game or after loading a game.
- *Start position*, *Clear board*, *Position (FEN)* and the piece palette set up
  any position, for example to test Scan.

Options: `--port` (web page, default 8081), `--link` (serial port symlink,
default `/tmp/dgt-sim`), `--picochess-url` (default `http://localhost:8080`),
`--fen` (starting placement).

## Limits

- No DGT clock is simulated; PicoChess uses its web clock instead.
- No Bluetooth pairing or battery status.
- Other board types (Certabo, ChessLink, Chessnut, …) use different protocols
  and are not simulated.
