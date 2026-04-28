import re
with open('multi_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the first CODER_SYSTEM_PROMPT end and next def coder_node
start_idx = content.find('CODER_SYSTEM_PROMPT = """')
print('Start idx:', start_idx)
end_of_first = content.find('"""', start_idx + 22)
print('End of first string:', end_of_first)
next_def = content.find('\ndef coder_node', end_of_first)
print('Next def coder_node:', next_def)

if end_of_first > 0 and next_def > end_of_first:
    new_content = content[:end_of_first + 3] + '\n\n\ndef coder_node' + content[next_def:]
    with open('multi_agent.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Fixed! Deleted ' + str(next_def - (end_of_first + 3)) + ' characters')
else:
    print('Error: end=' + str(end_of_first) + ', next=' + str(next_def))
