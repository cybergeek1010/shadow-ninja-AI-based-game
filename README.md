🥷 Ninja Stealth AI Game

A 2D stealth game developed in Python for an AI Techniques project. The game demonstrates how artificial intelligence algorithms can be used to create intelligent enemy behavior in a stealth-based environment.

🎯 Aim

To develop a 2D stealth game that uses Artificial Intelligence techniques to control guard behavior, detect the player, navigate through obstacles, and respond intelligently to the player's actions.

🎮 Game Concept

The player controls a ninja who must infiltrate an enemy area, avoid guards, collect the objective, and reach the exit without being detected.

Guards use different AI techniques to:

Patrol the environment
Detect the player
Chase the player
Search the player's last known location
Navigate around obstacles
React to player-generated noise
🧠 AI Techniques Used
1. Finite State Machine (FSM)

The guards operate using different states:

PATROL
   ↓
DETECT
   ↓
CHASE
   ↓
SEARCH
   ↓
PATROL

The guard changes its behavior depending on the player's location and whether the player is detected.

2. A* Pathfinding

The A* algorithm is used for intelligent navigation.

Instead of moving directly toward the player, the guard calculates a path through the map while avoiding walls and obstacles.

Guard
  ↓
A* Search
  ↓
Evaluate available paths
  ↓
Avoid obstacles
  ↓
Find optimal path
  ↓
Move toward target
3. Field of View

Guards have a limited vision range and field of view. The player is detected only when they are within the guard's visible area.

4. Line-of-Sight Detection

Walls can block the guard's vision. The guard cannot detect the player through obstacles.

5. Noise Detection

Player movement generates noise that can be detected by nearby guards. Guards can investigate the location where the noise was generated.

🕹️ Gameplay

The objective is to:

Enter the guarded area.
Avoid enemy guards.
Use walls and hiding areas for stealth.
Collect the objective.
Avoid detection.
Reach the exit safely.
✨ Features
2D top-down gameplay
Player movement
Wall collision
Guard patrol system
Intelligent guard behavior
Finite State Machine
A* pathfinding
Vision cone
Line-of-sight detection
Noise-based detection
Search behavior
Objective and exit system
Stealth-based gameplay
🛠️ Technologies Used
Python
Pygame
A Search Algorithm*
Finite State Machine
Object-Oriented Programming
📁 Project Structure
Ninja-Stealth/
│
├── main.py
├── player.py
├── guard.py
├── astar.py
├── map.py
├── assets/
│   ├── images/
│   └── sounds/
│
├── requirements.txt
└── README.md

The exact file structure may vary depending on the implementation.

🚀 Installation

Clone the repository:

git clone https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git

Navigate to the project directory:

cd Ninja-Stealth

Install the required dependencies:

pip install -r requirements.txt

Run the game:

python main.py
🎮 Controls
Key	Action
W	Move Up
A	Move Left
S	Move Down
D	Move Right
ESC	Exit Game

Controls may vary depending on the final implementation.

🧩 Algorithm Overview

The game combines multiple AI concepts rather than relying on simple scripted enemy movement.

                    NINJA
                      │
                      ↓
                Player Actions
                      │
          ┌───────────┴───────────┐
          ↓                       ↓
       Movement                  Noise
          │                       │
          ↓                       ↓
     Guard Vision          Hearing System
          │                       │
          └───────────┬───────────┘
                      ↓
                Guard AI / FSM
                      │
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
      PATROL        CHASE         SEARCH
        │             │             │
        └─────────────┼─────────────┘
                      ↓
                A* Pathfinding
                      ↓
                Avoid Obstacles
                      ↓
                 Guard Movement
🎓 Educational Purpose

This project demonstrates the practical application of Artificial Intelligence techniques in an interactive environment. It shows how search algorithms, state-based decision making, perception systems, and pathfinding can be combined to create intelligent game characters.

🔮 Future Improvements
Multiple guard types
More complex maps
Improved enemy AI
Advanced stealth mechanics
Distraction objects
Difficulty levels
Better animations and graphics
Sound-based environmental awareness
Multiple missions and levels
Score and ranking system
👨‍💻 Project

Project: Ninja Stealth AI Game
Type: AI Techniques Mini Project
Platform: PC
Language: Python
Framework: Pygame

📜 License

This project is created for educational and academic purposes.
