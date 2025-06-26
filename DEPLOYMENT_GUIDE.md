# LDA Group Time Tracking - Deployment Guide

## 📋 Updated Configuration Summary

Your application has been updated to work with your new infrastructure:

### Backend URL: `https://lda-backend-eyn4.onrender.com`
### Database: MongoDB Atlas cluster

---

## 🔧 Files to Update in Your GitHub Repository

### 1. Frontend Environment (`.env`)
```
WDS_SOCKET_PORT=443
REACT_APP_BACKEND_URL=https://lda-backend-eyn4.onrender.com
```

### 2. Backend Environment (`.env`)
```
MONGO_URL="mongodb+srv://dukemcintyredm:wanxszN3gukWLU61@ldagroup.yhjwyg7.mongodb.net/?retryWrites=true&w=majority&appName=ldagroup"
DB_NAME="lda_timetracking"
```

### 3. Updated Dependencies (`backend/requirements.txt`)
Key updates:
- `pymongo==4.13.2` (updated from 4.5.0)
- `motor==3.7.1` (updated from 3.3.1) 
- `pytz>=2024.1` (added for timezone support)

---

## 🗄️ Data Backup

Your complete application data has been backed up to:
- **File**: `lda_data_backup.json`
- **Contents**: 19 workers, 23 jobs, 25 time entries, 17 materials

---

## 🚀 Deployment Steps

### Step 1: Update GitHub Repository
1. Copy the updated `.env` files to your GitHub repository
2. Update `backend/requirements.txt` with the new dependencies
3. Copy `production_restore.py` and `lda_data_backup.json` to your repository
4. Push changes to GitHub

### Step 2: Deploy to Production
1. **Render Backend**: Should automatically redeploy when you push to GitHub
2. **Vercel Frontend**: Should automatically redeploy when you push to GitHub

### Step 3: Restore Your Data
1. After deployment, download `production_restore.py` and `lda_data_backup.json` to your local machine
2. Run the restoration script:
   ```bash
   python production_restore.py
   ```
3. This will restore your workers, jobs, and materials to the new database

### Step 4: Test Your Application
1. Access your frontend URL (Vercel deployment)
2. Test admin login: `admin` / `ldagroup2024`
3. Verify workers, jobs, and materials are present
4. Test time tracking functionality
5. Check attendance alerts and exports

---

## 🔧 Key Backend Changes Made

### MongoDB Connection Updates
- Updated to latest pymongo/motor versions for better Atlas compatibility
- Added proper SSL/TLS configuration for MongoDB Atlas
- Improved connection timeout and retry logic

### Timezone Support
- Added UK timezone support (BST/GMT automatic handling)
- Enhanced time display formatting
- Fixed time entry editing with proper timezone conversion

### Enhanced Features
- 7-day attendance alerts with export functionality
- Improved admin authentication persistence
- Fixed time entry editing endpoint

---

## 🔍 Troubleshooting

### If Backend Connection Fails:
1. Check Render dashboard for deployment logs
2. Verify environment variables are set correctly
3. Test MongoDB Atlas connection from Render

### If Data Restoration Fails:
1. Ensure backend is fully deployed and accessible
2. Check that admin credentials work
3. Try restoring data in smaller batches

### If Frontend Can't Connect:
1. Verify `REACT_APP_BACKEND_URL` points to your Render backend
2. Check CORS settings on backend
3. Ensure backend routes are prefixed with `/api`

---

## 🎯 Next Steps After Deployment

1. **Test all functionality** thoroughly
2. **Verify data integrity** - all workers, jobs, materials present
3. **Test time tracking** - clock in/out functionality
4. **Check reports and exports** - CSV downloads, attendance alerts
5. **Mobile responsiveness** - test on different devices

---

## 💾 Backup Strategy Going Forward

- Your MongoDB Atlas database now serves as your primary data store
- Consider setting up automated backups through MongoDB Atlas
- The `lda_data_backup.json` serves as a recovery point for this migration

---

✅ **Your LDA Group Time Tracking application is ready for production deployment!**