# Scavenger Hunt Educational Platform

An interactive QR-code based scavenger hunt system for educators and students.

**Live Demo:** [https://scavenger-hunt-1.onrender.com](https://scavenger-hunt-1.onrender.com)

## Features

### For Teachers:
- Create and manage scavenger hunts
- Add questions with multiple formats (text, multiple choice, image upload)
- Generate QR codes for physical locations
- Track student progress

### For Students:
- Scan QR codes to access questions
- Submit answers via text, multiple choice, or photos
- Receive hints and clues for next locations
- Track progress and scores

## Tech Stack

- **Backend:** Flask (Python)
- **Database:** SQLite (local) / PostgreSQL (production)
- **Frontend:** HTML, CSS, JavaScript
- **Authentication:** Flask-Bcrypt
- **Security:** Flask-WTF with CSRF protection
- **File Uploads:** Local storage

## Local Development

1. Clone the repository:
```bash
git clone https://github.com/yourusername/scavenger-hunt.git
cd scavenger-hunt
