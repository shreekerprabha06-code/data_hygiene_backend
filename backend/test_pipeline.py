import asyncio
from database import get_db, EXECUTION_INFO_COL
from validation import get_validator
from trigger import validate_document, standardize_document

async def test():
    db = get_db()
    validator = await get_validator()
    
    # Check for initiated docs
    doc = await db[EXECUTION_INFO_COL].find_one({'stage': 'validation initiated'})
    if doc:
        print('Validating document:', doc['_id'])
        try:
            await validate_document(db, validator, doc)
            print('Validation Success')
        except Exception as e:
            print('Validation Error:', e)
    else:
        print('No validation initiated docs found')
        
    # Check for standardization
    doc_std = await db[EXECUTION_INFO_COL].find_one({'stage': 'validation completed'})
    if doc_std:
        print('Standardizing document:', doc_std['_id'])
        try:
            await standardize_document(db, validator, doc_std)
            print('Standardization Success')
        except Exception as e:
            import traceback
            traceback.print_exc()
            print('Standardization Error:', e)
    else:
        print('No validation completed docs found')

asyncio.run(test())
